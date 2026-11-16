"""A local operator-owned marker stops admission without changing account policy."""
from pathlib import Path

from fastapi import HTTPException

from config import settings


def drain_path() -> Path:
    path = Path(settings.DEPLOYMENT_DRAIN_FILE).expanduser()
    return path if path.is_absolute() else Path(__file__).resolve().parents[1] / path


def draining() -> bool:
    return drain_path().exists()


def require_accepting() -> None:
    if draining():
        raise HTTPException(503, "服务正在更新，暂不接收新的生成请求，请稍后重试",
                            headers={"Retry-After": "30"})
