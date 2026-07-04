"""
api/policy.py — Policy document upload and conflict checking.

Routes:
  POST /api/policy/upload          — User uploads their internal policy (PDF)
  GET  /api/policy                 — List uploaded policy documents
  POST /api/policy/{id}/check      — Run conflict/impact check vs. live regulations
  GET  /api/policy/{id}/conflicts  — Get conflicts for a policy document
"""
import os
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import PolicyConflict, PolicyDocument
from app.db.session import get_db
from app.diffing.policy_classifier import get_domain_display_info

router = APIRouter(prefix="/api/policy", tags=["policy"])
settings = get_settings()


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class PolicyDocumentOut(BaseModel):
    id: int
    filename: str
    page_count: int
    ingested_at: str
    conflict_count: int
    policy_domain: str = ""
    domain_display: dict = {}

    class Config:
        from_attributes = True


class PolicyConflictOut(BaseModel):
    id: int
    policy_clause: str
    regulation_clause: str
    conflict: bool
    explanation: Optional[str]
    suggested_fix: Optional[str]
    conflict_score: float
    regulator: Optional[str]
    doc_title: Optional[str]
    detected_at: str

    class Config:
        from_attributes = True


class ConflictCheckResponse(BaseModel):
    status: str
    policy_id: int
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=PolicyDocumentOut)
async def upload_policy(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Accepts a PDF file upload, parses it, and stores it in the database.
    The policy is ready for conflict-checking against live regulations.
    """
    from fastapi import HTTPException

    # 1. Validate file type
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=422,
            detail="Only PDF files are accepted. Please upload a file with a .pdf extension."
        )

    # 2. Read content and check file size (20 MB limit)
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=422,
            detail="File too large — maximum allowed size is 20 MB. Please upload a smaller document."
        )

    # 3. Basic PDF magic bytes check (prevents renamed non-PDF files)
    if not content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=422,
            detail="This file does not appear to be a valid PDF. Please ensure it is a proper PDF document."
        )

    # 4. Check for duplicate filename — return existing policy if found
    existing = db.query(PolicyDocument).filter(PolicyDocument.filename == file.filename).first()
    if existing:
        return PolicyDocumentOut(
            id=existing.id,
            filename=existing.filename,
            page_count=existing.page_count,
            ingested_at=existing.ingested_at.isoformat(),
            conflict_count=len(existing.conflicts),
        )

    # 5. Save to disk
    upload_dir = os.path.join(settings.data_dir, "policies")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # 6. Parse the PDF — catch corruption or unreadable files
    from app.ingestion.parser import parse_pdf
    try:
        parsed = parse_pdf(file_path)
    except Exception as exc:
        # Clean up saved file on failure
        try:
            os.remove(file_path)
        except OSError:
            pass
        raise HTTPException(
            status_code=422,
            detail=f"Could not read this PDF — it may be corrupted or password-protected. Error: {exc}"
        )

    raw_text = parsed["text"]
    page_count = parsed["page_count"]

    # 7. Minimum text check — catches scanned/image-only PDFs
    if len(raw_text.strip()) < 200:
        try:
            os.remove(file_path)
        except OSError:
            pass
        raise HTTPException(
            status_code=422,
            detail=(
                "This appears to be a scanned or image-based PDF — very little text could be extracted. "
                f"Only {len(raw_text.strip())} characters found. "
                "Please upload a text-based PDF or a document with selectable text."
            )
        )

    # 8. Store in DB
    policy = PolicyDocument(
        filename=file.filename,
        file_path=file_path,
        raw_text=raw_text,
        page_count=page_count,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)

    return PolicyDocumentOut(
        id=policy.id,
        filename=policy.filename,
        page_count=policy.page_count,
        ingested_at=policy.ingested_at.isoformat(),
        conflict_count=0,
        policy_domain="",
        domain_display={},
    )


@router.get("", response_model=List[PolicyDocumentOut])
def list_policies(db: Session = Depends(get_db)):
    """Returns all uploaded policy documents."""
    policies = db.query(PolicyDocument).order_by(PolicyDocument.ingested_at.desc()).all()
    return [
        PolicyDocumentOut(
            id=p.id,
            filename=p.filename,
            page_count=p.page_count,
            ingested_at=p.ingested_at.isoformat(),
            conflict_count=len(p.conflicts),
            policy_domain=getattr(p, "policy_domain", "") or "",
            domain_display=get_domain_display_info(getattr(p, "policy_domain", "") or "General"),
        )
        for p in policies
    ]


@router.post("/{policy_id}/check", response_model=ConflictCheckResponse)
async def check_policy_conflicts(
    policy_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Runs the policy conflict analysis pipeline in the background.
    For each clause in the policy, retrieves relevant regulatory chunks
    and asks the LLM to identify conflicts.
    """
    policy = db.query(PolicyDocument).filter(PolicyDocument.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    from app.diffing.impact_analyzer import run_policy_conflict_check

    background_tasks.add_task(run_policy_conflict_check, policy_id=policy_id)

    return ConflictCheckResponse(
        status="started",
        policy_id=policy_id,
        message="Conflict analysis started. Check /api/policy/{id}/conflicts for results.",
    )


@router.get("/{policy_id}/status")
def get_policy_check_status(policy_id: int, db: Session = Depends(get_db)):
    """Returns the current status of the conflict checker for this policy."""
    policy = db.query(PolicyDocument).filter(PolicyDocument.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    from app.diffing.impact_analyzer import is_checking_policy
    is_processing = is_checking_policy(policy_id)
    
    return {
        "policy_id": policy_id,
        "is_processing": is_processing,
        "conflict_count": len(policy.conflicts)
    }


@router.get("/{policy_id}/conflicts", response_model=List[PolicyConflictOut])
def get_policy_conflicts(
    policy_id: int,
    conflict_only: bool = True,
    db: Session = Depends(get_db),
):
    """
    Returns all conflict check results for a policy document.
    By default, only returns rows where conflict=True.
    """
    policy = db.query(PolicyDocument).filter(PolicyDocument.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    query = db.query(PolicyConflict).filter(PolicyConflict.policy_id == policy_id)
    if conflict_only:
        query = query.filter(PolicyConflict.conflict == True)

    conflicts = query.order_by(PolicyConflict.conflict_score.desc()).all()

    result = []
    for c in conflicts:
        regulator = None
        doc_title = None
        if c.change_record and c.change_record.new_version and c.change_record.new_version.document:
            regulator = c.change_record.new_version.document.regulator
            doc_title = c.change_record.new_version.document.title

        result.append(
            PolicyConflictOut(
                id=c.id,
                policy_clause=c.policy_clause,
                regulation_clause=c.regulation_clause,
                conflict=c.conflict,
                explanation=c.explanation,
                suggested_fix=c.suggested_fix,
                conflict_score=c.conflict_score,
                regulator=regulator,
                doc_title=doc_title,
                detected_at=c.detected_at.isoformat(),
            )
        )
    return result


@router.get("/{policy_id}/export-pdf")
def export_policy_pdf(policy_id: int, db: Session = Depends(get_db)):
    """
    Generates a formatted compliance audit report as PDF using reportlab.
    Returns the PDF as a downloadable file response.
    """
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    import datetime as dt

    policy = db.query(PolicyDocument).filter(PolicyDocument.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")

    conflicts = (
        db.query(PolicyConflict)
        .filter(PolicyConflict.policy_id == policy_id, PolicyConflict.conflict == True)
        .order_by(PolicyConflict.conflict_score.desc())
        .all()
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title_style = ParagraphStyle("title", fontSize=18, fontName="Helvetica-Bold", spaceAfter=6, alignment=TA_CENTER)
    sub_style = ParagraphStyle("sub", fontSize=10, fontName="Helvetica", spaceAfter=4, alignment=TA_CENTER, textColor=colors.grey)
    body_style = ParagraphStyle("body", fontSize=9, fontName="Helvetica", spaceAfter=4, leading=13, alignment=TA_LEFT)
    h2_style = ParagraphStyle("h2", fontSize=12, fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=12, textColor=colors.HexColor("#d97706"))
    label_style = ParagraphStyle("label", fontSize=8, fontName="Helvetica-Bold", textColor=colors.grey, spaceAfter=2)

    story.append(Paragraph("Compliance Audit Report", title_style))
    story.append(Paragraph(f"Policy: {policy.filename}", sub_style))
    story.append(Paragraph(f"Generated: {dt.datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}", sub_style))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#d97706")))
    story.append(Spacer(1, 0.4*cm))

    # Summary
    story.append(Paragraph("Summary", h2_style))
    summary_data = [
        ["Policy File", policy.filename],
        ["Page Count", str(policy.page_count)],
        ["Conflicts Found", str(len(conflicts))],
        ["Analysis Date", dt.datetime.utcnow().strftime("%d %b %Y")],
    ]
    t = Table(summary_data, colWidths=[5*cm, 12*cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.6*cm))

    # Conflicts
    if conflicts:
        story.append(Paragraph(f"Detected Conflicts ({len(conflicts)})", h2_style))
        for i, c in enumerate(conflicts, 1):
            story.append(Paragraph(f"Conflict #{i} — Score: {c.conflict_score*100:.0f}%", label_style))
            if c.policy_clause:
                story.append(Paragraph(f"<b>Your Policy:</b> {c.policy_clause[:500]}", body_style))
            if c.regulation_clause:
                story.append(Paragraph(f"<b>Regulation:</b> {c.regulation_clause[:500]}", body_style))
            if c.explanation:
                story.append(Paragraph(f"<b>Analysis:</b> {c.explanation[:500]}", body_style))
            if c.suggested_fix:
                story.append(Paragraph(f"<b>Suggested Fix:</b> {c.suggested_fix[:500]}", body_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e5e7eb")))
            story.append(Spacer(1, 0.3*cm))
    else:
        story.append(Paragraph("No conflicts detected.", body_style))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="compliance-report-{policy_id}.pdf"'},
    )
