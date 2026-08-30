from fastapi import APIRouter, UploadFile

from .. import facebook
from ..schemas import LoginStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=LoginStatus)
def status() -> LoginStatus:
    info = facebook.cookie_status()
    return LoginStatus(
        logged_in=info["cookies_present"],
        cookies_present=info["cookies_present"],
        expired=info["expired"],
        expires_at=info["expires_at"],
        days_remaining=info["days_remaining"],
    )


@router.post("/cookies", response_model=LoginStatus)
async def upload_cookies(file: UploadFile) -> LoginStatus:
    """Uploads the cookies.txt file (Netscape format) exported from the
    browser. A password is never requested or stored."""
    raw = await file.read()
    facebook.save_cookies(raw)
    info = facebook.cookie_status()
    return LoginStatus(
        logged_in=True,
        cookies_present=True,
        expired=info["expired"],
        expires_at=info["expires_at"],
        days_remaining=info["days_remaining"],
    )


@router.delete("/cookies", response_model=LoginStatus)
def logout() -> LoginStatus:
    facebook.clear_cookies()
    return LoginStatus(logged_in=False, cookies_present=False)
