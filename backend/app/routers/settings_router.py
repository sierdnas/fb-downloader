from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..config import settings
from ..db import get_session
from ..models import AppSettings
from ..schemas import SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

_PERSISTED_KEYS = (
    "filename_template",
    "filename_template_photo",
    "folder_template_video",
    "folder_template_photo",
    "date_format",
    "generate_nfo",
    "ui_language",
    "log_level",
    "theme",
    "translate_description",
)

_BOOL_KEYS = ("generate_nfo", "translate_description")


def load_persisted_settings(session: Session) -> None:
    """Called at startup: overrides the defaults with any values saved in the DB."""
    for row in session.exec(select(AppSettings).where(AppSettings.key.in_(_PERSISTED_KEYS))):
        if row.key in _BOOL_KEYS:
            setattr(settings, row.key, row.value == "true")
        elif row.key == "log_level":
            try:
                setattr(settings, row.key, int(row.value))
            except ValueError:
                pass
        else:
            setattr(settings, row.key, row.value)


def _persist(session: Session, key: str, value: str) -> None:
    row = session.get(AppSettings, key)
    if row:
        row.value = value
    else:
        row = AppSettings(key=key, value=value)
    session.add(row)


@router.get("")
def get_settings() -> dict:
    return {
        "filename_template": settings.filename_template,
        "filename_template_photo": settings.filename_template_photo,
        "folder_template_video": settings.folder_template_video,
        "folder_template_photo": settings.folder_template_photo,
        "date_format": settings.date_format,
        "generate_nfo": settings.generate_nfo,
        "ui_language": settings.ui_language,
        "log_level": settings.log_level,
        "theme": settings.theme,
        "translate_description": settings.translate_description,
        # read-only: reflects whether FACEBOOK_ACCESS_TOKEN is set in
        # .env — the value itself is NEVER exposed here or stored in the
        # DB, only this yes/no flag (see nfo.py/config.py for why)
        "facebook_access_token_configured": bool(settings.facebook_access_token),
        "media_root": str(settings.media_root),
        "photo_media_root": str(settings.photo_media_root),
        "available_tokens": ["{date}", "{profile}", "{title}", "{id}", "{type}", "{season}"],
    }


@router.put("")
def update_settings(update: SettingsUpdate, session: Session = Depends(get_session)) -> dict:
    if update.filename_template is not None:
        settings.filename_template = update.filename_template
        _persist(session, "filename_template", update.filename_template)
    if update.filename_template_photo is not None:
        settings.filename_template_photo = update.filename_template_photo
        _persist(session, "filename_template_photo", update.filename_template_photo)
    if update.folder_template_video is not None:
        settings.folder_template_video = update.folder_template_video
        _persist(session, "folder_template_video", update.folder_template_video)
    if update.folder_template_photo is not None:
        settings.folder_template_photo = update.folder_template_photo
        _persist(session, "folder_template_photo", update.folder_template_photo)
    if update.date_format is not None:
        settings.date_format = update.date_format
        _persist(session, "date_format", update.date_format)
    if update.generate_nfo is not None:
        settings.generate_nfo = update.generate_nfo
        _persist(session, "generate_nfo", "true" if update.generate_nfo else "false")
    if update.ui_language is not None:
        settings.ui_language = update.ui_language
        _persist(session, "ui_language", update.ui_language)
    if update.log_level is not None:
        settings.log_level = update.log_level
        _persist(session, "log_level", str(update.log_level))
    if update.theme is not None:
        settings.theme = update.theme
        _persist(session, "theme", update.theme)
    if update.translate_description is not None:
        settings.translate_description = update.translate_description
        _persist(session, "translate_description", "true" if update.translate_description else "false")

    session.commit()
    return get_settings()
