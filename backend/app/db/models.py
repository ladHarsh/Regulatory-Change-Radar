"""
db/models.py — SQLAlchemy ORM models for the Regulatory Change Radar.

Tables:
  - Document         : A regulatory document source (e.g., a specific RBI circular series)
  - DocumentVersion  : Each scraped version of a document, tracked over time
  - DocumentChunk    : Individual text chunks stored in ChromaDB + SQLite metadata
  - ChangeRecord     : Semantic diff result between two document versions
  - PolicyDocument   : User-uploaded internal policy
  - PolicyConflict   : Detected conflict between a policy clause and a regulation
  - QueryLog         : User RAG queries for audit trail
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    """
    A regulatory document — represents a unique circular/guideline identified by URL or title.
    A Document can have many DocumentVersions over time.
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    regulator = Column(String(20), nullable=False, index=True)   # "RBI" | "SEBI" | "IRDAI"
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False, unique=True)
    doc_type = Column(String(50), default="circular")            # circular | guideline | notification
    created_at = Column(DateTime, default=datetime.utcnow)

    versions = relationship("DocumentVersion", back_populates="document", cascade="all, delete-orphan")


class DocumentVersion(Base):
    """
    A specific ingested version of a Document.
    Content hash lets us detect when a document has actually changed.
    """
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "content_hash", name="uq_doc_version_hash"),)

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    version_num = Column(Integer, nullable=False, default=1)
    content_hash = Column(String(64), nullable=False)   # MD5 of raw_text
    raw_text = Column(Text, nullable=False)
    file_path = Column(String(500), nullable=True)       # local path to saved PDF/HTML
    page_count = Column(Integer, default=0)
    ingested_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="versions")
    chunks = relationship("DocumentChunk", back_populates="version", cascade="all, delete-orphan")
    changes_as_old = relationship("ChangeRecord", foreign_keys="ChangeRecord.old_version_id", back_populates="old_version")
    changes_as_new = relationship("ChangeRecord", foreign_keys="ChangeRecord.new_version_id", back_populates="new_version")


class DocumentChunk(Base):
    """
    A single text chunk from a document version.
    The chunk_id corresponds to the ChromaDB document ID for vector lookup.
    """
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_id = Column(String(100), nullable=False, unique=True)  # ChromaDB ID
    text = Column(Text, nullable=False)
    page_num = Column(Integer, default=0)
    section_ref = Column(String(200), nullable=True)              # e.g., "Section 4.2"
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    version = relationship("DocumentVersion", back_populates="chunks")


class ChangeRecord(Base):
    """
    Result of the semantic diff between two document versions.
    One row per changed clause (MODIFIED, NEW, or REMOVED).
    """
    __tablename__ = "change_records"

    id = Column(Integer, primary_key=True, index=True)
    old_version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=True, index=True)
    new_version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False, index=True)

    # Change classification
    change_type = Column(String(20), nullable=False)   # UNCHANGED | MODIFIED | NEW | REMOVED
    similarity_score = Column(Float, nullable=True)

    # Clause text
    old_clause = Column(Text, nullable=True)
    new_clause = Column(Text, nullable=True)
    old_section_ref = Column(String(200), nullable=True)
    new_section_ref = Column(String(200), nullable=True)

    # LLM-generated impact analysis
    impact_summary = Column(Text, nullable=True)
    affected_area = Column(String(500), nullable=True)
    risk_direction = Column(String(20), nullable=True)  # increased | decreased | unchanged
    severity = Column(String(10), nullable=True)         # High | Medium | Low (derived from risk_direction)

    detected_at = Column(DateTime, default=datetime.utcnow)

    old_version = relationship("DocumentVersion", foreign_keys=[old_version_id], back_populates="changes_as_old")
    new_version = relationship("DocumentVersion", foreign_keys=[new_version_id], back_populates="changes_as_new")
    policy_conflicts = relationship("PolicyConflict", back_populates="change_record")


class PolicyDocument(Base):
    """
    An internal policy document uploaded by the user.
    """
    __tablename__ = "policy_documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(500), nullable=False)
    file_path = Column(String(500), nullable=True)
    raw_text = Column(Text, nullable=False)
    page_count = Column(Integer, default=0)
    ingested_at = Column(DateTime, default=datetime.utcnow)

    # Domain classification (populated when conflict check runs)
    policy_domain = Column(String(100), default="")              # e.g., "KYC", "AML", "Securities"
    policy_domain_confidence = Column(Float, default=0.0)        # 0-1 classifier confidence

    conflicts = relationship("PolicyConflict", back_populates="policy_document", cascade="all, delete-orphan")


class PolicyConflict(Base):
    """
    A detected conflict between a policy clause and a regulatory change.
    """
    __tablename__ = "policy_conflicts"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policy_documents.id"), nullable=False, index=True)
    change_record_id = Column(Integer, ForeignKey("change_records.id"), nullable=True, index=True)

    policy_clause = Column(Text, nullable=False)
    regulation_clause = Column(Text, nullable=False)
    conflict = Column(Boolean, nullable=False, default=False)
    explanation = Column(Text, nullable=True)
    suggested_fix = Column(Text, nullable=True)
    conflict_score = Column(Float, default=0.0)   # 0–1 severity
    detected_at = Column(DateTime, default=datetime.utcnow)

    policy_document = relationship("PolicyDocument", back_populates="conflicts")
    change_record = relationship("ChangeRecord", back_populates="policy_conflicts")


class QueryLog(Base):
    """
    Audit log of all user RAG queries.
    Extended with pipeline-stage tracking fields for the evaluation dashboard.
    """
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, index=True)
    query_text = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    sources_json = Column(Text, nullable=True)      # JSON array of source metadata
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Pipeline v3 fields
    query_type = Column(String(20), nullable=True)          # factual|eligibility|scenario|comparison
    verified = Column(Boolean, nullable=True)               # Verification Agent result
    stage_timings_json = Column(Text, nullable=True)        # JSON {stage: ms}
    retrieval_confidence = Column(Float, nullable=True)     # top reranker score
    reasoning_path = Column(String(20), nullable=True)      # structured|chain_of_thought|factual
    fallback_used = Column(Boolean, default=False)

class Bookmark(Base):
    """
    User-bookmarked documents or change records (single-user app).
    """
    __tablename__ = "bookmarks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    change_record_id = Column(Integer, ForeignKey("change_records.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", foreign_keys=[document_id])
    change_record = relationship("ChangeRecord", foreign_keys=[change_record_id])


class Notification(Base):
    """
    In-app notifications for high-severity regulatory changes.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), default="high_severity")  # high_severity | new_document | etc.
    title = Column(String(500), nullable=False)
    message = Column(Text, nullable=False)
    read = Column(Boolean, default=False)
    change_record_id = Column(Integer, ForeignKey("change_records.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    change_record = relationship("ChangeRecord", foreign_keys=[change_record_id])


# ── Evaluation tables ─────────────────────────────────────────────────────────

class EvalTestCase(Base):
    """
    A labeled test case for the evaluation suite.
    Each case has a question, expected answer, and keywords that should appear
    in the retrieved chunks (for Recall@k computation).
    """
    __tablename__ = "eval_test_cases"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=False)
    expected_chunk_keywords = Column(Text, nullable=True)  # JSON list of keywords
    query_type = Column(String(20), default="factual")     # factual|eligibility|scenario
    created_at = Column(DateTime, default=datetime.utcnow)

    results = relationship("EvalResult", back_populates="test_case", cascade="all, delete-orphan")


class EvalRun(Base):
    """
    Summary of a complete evaluation suite run.
    Stores aggregate metrics for the evaluation dashboard trend charts.
    """
    __tablename__ = "eval_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_at = Column(DateTime, default=datetime.utcnow)
    total_cases = Column(Integer, default=0)
    retrieval_accuracy = Column(Float, nullable=True)   # Recall@5
    answer_accuracy = Column(Float, nullable=True)      # LLM-as-judge avg 1-5
    hallucination_rate = Column(Float, nullable=True)   # % verified=False
    avg_latency_ms = Column(Float, nullable=True)
    p95_latency_ms = Column(Float, nullable=True)

    results = relationship("EvalResult", back_populates="run", cascade="all, delete-orphan")


class EvalResult(Base):
    """
    Per-question result from a single evaluation run.
    Drives the per-question breakdown table in the dashboard.
    """
    __tablename__ = "eval_results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("eval_runs.id"), nullable=False, index=True)
    test_case_id = Column(Integer, ForeignKey("eval_test_cases.id"), nullable=False, index=True)

    generated_answer = Column(Text, nullable=True)
    retrieved_correct = Column(Boolean, nullable=True)
    answer_score = Column(Float, nullable=True)         # LLM-as-judge 1-5
    verified = Column(Boolean, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    stage_timings_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("EvalRun", back_populates="results")
    test_case = relationship("EvalTestCase", back_populates="results")

