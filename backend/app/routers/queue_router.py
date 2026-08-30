from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..models import MediaItem

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("", response_model=list[MediaItem])
def get_queue(session: Session = Depends(get_session)) -> list[MediaItem]:
    """Items currently queued or downloading, in insertion order. Used
    by the web UI for progress polling after starting a download (which
    is now asynchronous and no longer blocks the HTTP request)."""
    query = (
        select(MediaItem)
        .where(MediaItem.status.in_(["queued", "downloading"]))
        .order_by(MediaItem.created_at)
    )
    return session.exec(query).all()
