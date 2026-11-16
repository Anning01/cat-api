"""A local operator-owned marker stops admission without changing account policy."""
from pathlib import Path
from functools import lru_cache
import subprocess
from uuid import uuid4

from fastapi import HTTPException

from config import settings

INSTANCE_ID = uuid4().hex


@lru_cache(maxsize=1)
def release_commit() -> str:
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=2, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def drain_path() -> Path:
    path = Path(settings.DEPLOYMENT_DRAIN_FILE).expanduser()
    return path if path.is_absolute() else Path(__file__).resolve().parents[1] / path


def draining() -> bool:
    return drain_path().exists()


def require_accepting() -> None:
    if draining():
        raise HTTPException(503, "服务正在更新，暂不接收新的生成请求，请稍后重试",
                            headers={"Retry-After": "30"})
