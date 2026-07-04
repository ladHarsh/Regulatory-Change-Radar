"""
api/notifications.py — In-app notification endpoints for v2.0.

Routes:
  GET  /api/notifications          — List notifications (latest 50)
  POST /api/notifications/{id}/read — Mark a notification as read
  POST /api/notifications/read-all  — Mark all as read
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Notification
from app.db.session import get_db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: str
    read: bool
    change_record_id: int | None
    created_at: str

    class Config:
        from_attributes = True


class NotifCountOut(BaseModel):
    unread_count: int


@router.get("", response_model=List[NotificationOut])
def list_notifications(db: Session = Depends(get_db)):
    notifs = (
        db.query(Notification)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        NotificationOut(
            id=n.id,
            type=n.type,
            title=n.title,
            message=n.message,
            read=n.read,
            change_record_id=n.change_record_id,
            created_at=n.created_at.isoformat(),
        )
        for n in notifs
    ]


@router.get("/unread-count", response_model=NotifCountOut)
def unread_count(db: Session = Depends(get_db)):
    count = db.query(Notification).filter(Notification.read == False).count()  # noqa: E712
    return NotifCountOut(unread_count=count)


@router.post("/{notif_id}/read", status_code=200)
def mark_read(notif_id: int, db: Session = Depends(get_db)):
    notif = db.query(Notification).filter(Notification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all", status_code=200)
def mark_all_read(db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.read == False).update({"read": True})  # noqa: E712
    db.commit()
    return {"ok": True}
