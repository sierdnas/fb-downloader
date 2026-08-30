"""
Template engine for folder/file names, inspired by Radarr.

Tokens supported in FILENAME_TEMPLATE / FOLDER_TEMPLATE:
    {date}     publish date, formatted with DATE_FORMAT (default YYYY-MM-DD)
    {profile}  name of the source Facebook profile/page
    {title}    post title/text, "slugified"
    {id}       Facebook post/media id (unique, also used for deduplication)
    {type}     media type: Video / Photo / Reel
    {season}   publish year, used to organize video/reel as "seasons" of
               a TV show in Jellyfin (Show = profile)

Rules:
    - the PHYSICAL name (file/folder on disk) NEVER contains spaces:
      spaces are converted to underscore "_"
    - characters not allowed by the filesystem (/ \\ : * ? " < > | and
      similar) are removed
    - accented/"weird" unicode characters are normalized (unidecode)
    - the readable title (no underscores, with spaces) is kept ONLY in
      metadata (DB + optional .nfo for Jellyfin), never in the physical name
"""
import re
from datetime import date, datetime

from unidecode import unidecode

# Characters forbidden or problematic on common filesystems (NTFS/exFAT/ext4/SMB)
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_UNDERSCORE = re.compile(r"_+")
_MULTI_SPACE = re.compile(r"\s+")


def slugify_physical(text: str, max_len: int = 120) -> str:
    """Converts a string into a form safe for file/folder names: no
    spaces (-> underscore), no unicode/accented characters, no
    characters forbidden by the filesystem."""
    if not text:
        return "untitled"
    text = unidecode(text)                       # remove accents/unicode
    text = _INVALID_CHARS.sub("", text)           # remove forbidden characters
    text = _MULTI_SPACE.sub(" ", text).strip()    # normalize multiple spaces
    text = text.replace(" ", "_")                 # space -> underscore
    text = _MULTI_UNDERSCORE.sub("_", text)       # multiple underscores -> single
    text = text.strip("._")
    return text[:max_len] or "untitled"


def clean_display_title(text: str) -> str:
    """Readable title for Jellyfin/UI: normal spaces, no forced
    underscores. Used ONLY in metadata (.nfo, DB), never in the
    physical filename."""
    if not text:
        return "Untitled"
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text


MEDIA_TYPE_LABELS = {
    "video": "Video",
    "photo": "Photo",
    "reel": "Reel",
}


def format_display_title(fb_id: str, publish_date: "datetime | date | None") -> str:
    """Readable title for the media (used BOTH in the .nfo AND in the web
    UI, to stay consistent): date, time, and Facebook ID separated by
    spaces, with a dash instead of colons in the time — e.g.
    "2026-08-16 23-50 2128650394390172". No underscores: those only
    exist in the physical filename on disk."""
    if publish_date:
        return f"{publish_date.strftime('%Y-%m-%d')} {publish_date.strftime('%H-%M')} {fb_id}"
    return f"Unknown date {fb_id}"


def render_template(
    template: str,
    *,
    publish_date: "datetime | date | None",
    profile: str,
    title: str,
    media_id: str,
    media_type: str,
    date_format: str = "%Y-%m-%d",
    season: "int | None" = None,
    post_id: "str | None" = None,
) -> str:
    """Renders a template (file or folder name) by substituting tokens.
    Each individual component is sanitized BEFORE substitution, so even
    nested templates (e.g. "{profile}/Stagione {season}") stay safe.

    {season}: if not passed explicitly, it's derived from the year of
    publish_date (used to organize videos/reels as "seasons" of a TV
    show in Jellyfin, one per Facebook profile).

    {post_id}: identity of the POST (stable), distinct from {id} which
    instead identifies the individual media item and may have a
    disambiguation suffix (e.g. "-2") when multiple photos from the same
    post would otherwise share the same ID — used to group all photos
    from a post into the same folder. Falls back to {id} if not passed
    explicitly."""
    date_str = publish_date.strftime(date_format) if publish_date else "0000-00-00"
    type_label = MEDIA_TYPE_LABELS.get(media_type, media_type.capitalize())
    season_value = season if season is not None else (publish_date.year if publish_date else 0)
    post_id_value = post_id if post_id is not None else media_id

    values = {
        "date": date_str,
        "profile": slugify_physical(profile),
        "title": slugify_physical(title),
        "id": slugify_physical(str(media_id)),
        "type": slugify_physical(type_label),
        "season": str(season_value),
        "post_id": slugify_physical(str(post_id_value)),
    }

    try:
        rendered = template.format(**values)
    except (KeyError, IndexError) as exc:
        raise ValueError(f"Unknown token in template: {exc}") from exc

    # extra safety: a "/" in the template is intentional (folder
    # separator), but must NEVER appear inside a single token already
    # sanitized above
    return rendered


def build_relative_path(
    folder_template: str,
    filename_template: str,
    extension: str,
    **kwargs,
) -> str:
    """Builds the full relative path (folder/filename.ext)."""
    folder = render_template(folder_template, **kwargs)
    filename = render_template(filename_template, **kwargs)
    ext = extension.lstrip(".")
    return f"{folder}/{filename}.{ext}"
