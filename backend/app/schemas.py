from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    url: str
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class MediaPreview(BaseModel):
    fb_id: str
    post_id: Optional[str] = None  # stable post identity, see naming.render_template
    source_url: str
    profile: str
    profile_id: Optional[str] = None
    media_type: str          # video | photo | reel
    title: str
    display_title: str       # date-time + ID, e.g. "2026-08-16 23-50 2128650394390172" — shown in UI and in the .nfo
    description: Optional[str] = None
    tags: list[str] = []
    publish_date: Optional[datetime] = None
    thumbnail_url: Optional[str] = None
    already_downloaded: bool = False
    predicted_path: str      # preview of the final path, with current templates


class AnalyzeResponse(BaseModel):
    profile: str
    items: list[MediaPreview]


class AnalyzeJobStatus(BaseModel):
    job_id: str
    status: str  # running | done | error
    profile: Optional[str] = None
    items: Optional[list[MediaPreview]] = None
    error: Optional[str] = None


class DownloadRequest(BaseModel):
    items: list[MediaPreview]
    media_types: list[str] = ["video", "photo", "reel"]  # filter of types to download


class SettingsUpdate(BaseModel):
    filename_template: Optional[str] = None
    filename_template_photo: Optional[str] = None
    folder_template_video: Optional[str] = None
    folder_template_photo: Optional[str] = None
    date_format: Optional[str] = None
    generate_nfo: Optional[bool] = None
    ui_language: Optional[str] = None
    log_level: Optional[int] = None


class LoginStatus(BaseModel):
    logged_in: bool
    cookies_present: bool
    expired: Optional[bool] = None
    expires_at: Optional[str] = None
    days_remaining: Optional[int] = None
