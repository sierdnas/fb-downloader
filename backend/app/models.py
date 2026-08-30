from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class MediaItem(SQLModel, table=True):
    """A single media item (video/photo/reel) tracked in the download history."""

    id: Optional[int] = Field(default=None, primary_key=True)

    # Facebook post/media identifier: anti-duplicate key
    fb_id: str = Field(index=True, unique=True)
    source_url: str

    profile: str = Field(index=True)
    media_type: str  # "video" | "photo" | "reel"

    # "title" = computed date-time + ID title (same format as the .nfo,
    # e.g. "2026-08-16 23-50 2128650394390172") — NOT the raw post text,
    # which lives in "description" instead.
    title: str
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    publish_date: Optional[datetime] = None

    # Physical path relative to MEDIA_ROOT, already rendered by the naming engine
    relative_path: str

    # Video/reel only: organized as episodes of a "TV show" per profile
    # in Jellyfin. season = publish year, episode = chronological
    # progressive number within the season. None for photos.
    season: Optional[int] = None
    episode: Optional[int] = None

    status: str = Field(default="pending")  # pending|downloading|done|error|skipped_duplicate
    error_message: Optional[str] = None

    file_size_bytes: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    downloaded_at: Optional[datetime] = None


class AnalyzedSource(SQLModel, table=True):
    """History of analyzed links (profile/post/page), so they can be
    reloaded with one click to re-run analysis/download without having
    to find the original URL again."""

    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(index=True, unique=True)
    profile: Optional[str] = None
    last_item_count: int = Field(default=0)
    first_analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    last_analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class AppSettings(SQLModel, table=True):
    """Persistent settings editable from the UI (simple key/value)."""

    key: str = Field(primary_key=True)
    value: str
