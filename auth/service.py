"""猫影用户会话服务。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from utils.messages import localized_message
from utils.enums import UserStatusEnum

from auth.models import QilingIdentity, User, UserSession
from auth.schemas import LoginIn, RegisterIn, LoginOut, MeOut, UserOut
from auth.security import hash_password, verify_password, hash_token, new_session_token
from config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    """发放和撤销本地会话并返回账户账户身份。"""

    async def login(self, data: LoginIn) -> LoginOut:
        user = await User.get_or_none(username=data.username.strip())
        if user is None or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail=localized_message('用户名或密码错误'))
        if user.status != UserStatusEnum.active.value:
            raise HTTPException(status_code=403, detail=localized_message('账号已停用，请联系管理员'))
        return await self.issue_session(user)

    async def register(self, data: RegisterIn) -> LoginOut:
        if await User.filter(username=data.username.strip()).exists():
            raise HTTPException(400, "用户名已存在")
        user = await User.create(username=data.username.strip(), nickname=data.nickname,
                                 password_hash=hash_password(data.password))
        return await self.issue_session(user)

    async def issue_session(self, user: User) -> LoginOut:
        token = new_session_token()
        await UserSession.create(
            token_hash=hash_token(token),
            user=user,
            expires_at=_now() + timedelta(hours=settings.SESSION_TTL_HOURS),
        )
        return LoginOut(token=token, user=UserOut.model_validate(user))

    async def me(self, user: User) -> MeOut:
        from services.balance import get_balance
        from services.billing.aggregation import summary
        totals = await summary(account_user_id=user.id)
        return MeOut(user=UserOut.model_validate(user), is_super_admin=user.is_super_admin,
                     balance=await get_balance(user.id), total_cost=totals["total_cost"],
                     qiling_bound=await QilingIdentity.filter(user_id=user.id).exists())

    async def logout(self, token: str | None) -> None:
        if token:
            await UserSession.filter(token_hash=hash_token(token)).delete()

    async def change_password(
        self, user: User, old_password: str, new_password: str
    ) -> None:
        if not verify_password(old_password, user.password_hash):
            raise HTTPException(status_code=400, detail=localized_message('当前密码不正确'))
        user.password_hash = hash_password(new_password)
        await user.save(update_fields=["password_hash", "updated_at"])


auth_service = AuthService()
