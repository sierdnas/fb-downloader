"""
Facebook login in "mode B": session cookies only, NEVER the password.

Flow:
    1. The user logs in to facebook.com in their own browser (outside the app)
    2. Exports cookies in Netscape format (e.g. the "Get cookies.txt" extension)
    3. Uploads the cookies.txt file in the web UI -> saved to /config
    4. yt-dlp / gallery-dl use that file for authenticated requests

A password is never handled or requested inside the app.

Expiry detection: the Netscape cookie format includes, for each line, a
Unix expiry timestamp — we read it directly from the file, with no need
to make test requests to Facebook (more reliable: a download error can
depend on a thousand other things, the expiry date can't).
"""
from datetime import datetime
from pathlib import Path

from .config import settings

# Cookies that identify an authenticated Facebook session; their expiry
# is what really matters to know whether the login is still valid
CRITICAL_COOKIES = ("xs", "c_user")


def save_cookies(raw_bytes: bytes) -> None:
    settings.cookies_path.write_bytes(raw_bytes)


def cookies_present() -> bool:
    return settings.cookies_path.exists() and settings.cookies_path.stat().st_size > 0


def clear_cookies() -> None:
    if settings.cookies_path.exists():
        settings.cookies_path.unlink()


def cookies_file_path() -> "Path | None":
    return settings.cookies_path if cookies_present() else None


def build_cookie_header(domain_filter: str = "facebook.com") -> str:
    """Builds a "name=value; name2=value2" Cookie header string from the
    cookies.txt file (Netscape format), for the direct HTTP requests
    this app makes itself (poster/fanart fetching in nfo.py) — yt-dlp
    and gallery-dl already get the whole file via --cookies, but those
    are separate, ad-hoc urllib requests that otherwise go out
    completely anonymous even when a valid session is configured, which
    can matter: some of Facebook's endpoints behave differently (e.g.
    returning the generic placeholder silhouette instead of the real
    picture) for anonymous vs authenticated requests. Only includes
    cookies whose domain matches domain_filter (a leading "." in the
    file, meaning "this and all subdomains", still matches). Returns an
    empty string if no cookies file is present or nothing matches."""
    if not cookies_present():
        return ""

    pairs: list[str] = []
    for raw_line in settings.cookies_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not line.startswith("#HttpOnly_"):
                continue
            line = line[len("#HttpOnly_"):]

        parts = line.split("\t")
        if len(parts) < 7:
            continue

        domain, _flag, _path, _secure, _expiry, name, value = parts[:7]
        domain_bare = domain.lstrip(".")
        if domain_bare != domain_filter and not domain_bare.endswith("." + domain_filter):
            continue

        pairs.append(f"{name}={value}")

    return "; ".join(pairs)


def _parse_cookie_expiries(cookies_path: Path) -> dict[str, datetime]:
    """Extracts {cookie_name: expiry_date} from the cookies.txt file
    (Netscape format). Cookies with expiry 0 are "session" cookies (no
    fixed expiry in the file) and are ignored here."""
    result: dict[str, datetime] = {}
    if not cookies_path.exists():
        return result

    for raw_line in cookies_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not line.startswith("#HttpOnly_"):
                continue
            line = line[len("#HttpOnly_"):]

        parts = line.split("\t")
        if len(parts) < 7:
            continue

        name = parts[5]
        try:
            expiry_ts = int(parts[4])
        except ValueError:
            continue

        if expiry_ts > 0:
            try:
                result[name] = datetime.utcfromtimestamp(expiry_ts)
            except (ValueError, OSError):
                continue

    return result


def cookie_status() -> dict:
    """Session validity status: expired, expiring in N days, or with no
    readable expiry information from the file."""
    if not cookies_present():
        return {"cookies_present": False, "expired": None, "expires_at": None, "days_remaining": None}

    expiries = _parse_cookie_expiries(settings.cookies_path)
    critical = [v for k, v in expiries.items() if k in CRITICAL_COOKIES]
    relevant = critical or list(expiries.values())

    if not relevant:
        # file present but with no readable expiry dates (e.g. only
        # session cookies): we can't say anything for certain
        return {"cookies_present": True, "expired": None, "expires_at": None, "days_remaining": None}

    soonest = min(relevant)
    now = datetime.utcnow()
    return {
        "cookies_present": True,
        "expired": soonest < now,
        "expires_at": soonest.isoformat(),
        "days_remaining": (soonest - now).days,
    }
