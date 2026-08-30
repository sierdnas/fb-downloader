from fastapi import APIRouter
from pydantic import BaseModel

from .. import log_buffer

router = APIRouter(prefix="/api/logs", tags=["logs"])


class LogsResponse(BaseModel):
    lines: list[str]


@router.get("", response_model=LogsResponse)
def read_logs() -> LogsResponse:
    return LogsResponse(lines=log_buffer.get_logs())


@router.delete("")
def clear_logs() -> dict:
    log_buffer.clear_logs()
    return {"cleared": True}
