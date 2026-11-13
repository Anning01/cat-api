"""鉴权 API 的请求/响应模型。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from config import settings


def _serialize_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime(settings.DATETIME_FORMAT)


def _serialize_money(value: Decimal | None) -> float:
    try:
        return round(float(value or 0), 6)
    except (TypeError, ValueError):
        return 0.0


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100, description="用户名")
    password: str = Field(min_length=1, max_length=200, description="密码")


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=200, description="当前密码")
    new_password: str = Field(
        min_length=8, max_length=200, description="新密码（至少 8 位）"
    )


class RegisterIn(BaseModel):
    """经邀请链接注册新账号。"""

    username: str = Field(min_length=1, max_length=100, description="用户名")
    password: str = Field(min_length=8, max_length=200, description="密码（至少 8 位）")
    nickname: str = Field("", max_length=100, description="昵称")


class ProfileUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nickname: str = Field(min_length=1, max_length=100)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str = ""
    avatar_url: str = ""
    is_super_admin: bool = False
    created_at: datetime | str | None = ""

    @field_serializer("avatar_url")
    def _ser_avatar_url(self, value):
        from services.oss import resolve_media_url
        return resolve_media_url(value) or ""

    @field_serializer("created_at", when_used="json")
    def _ser_created_at(self, value):
        return _serialize_datetime(value)


class MeOut(BaseModel):
    """当前用户信息 + 账户账户身份 + 累计消耗（用户中心展示）。"""

    user: UserOut
    balance: Decimal = Decimal("0")
    is_super_admin: bool = False
    total_cost: float = 0.0
    qiling_bound: bool = False


class LoginOut(BaseModel):
    token: str
    user: UserOut
