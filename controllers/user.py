"""用户管理控制器（仅超级管理员）：列表、统计、禁用登录和删除。"""

from utils.messages import localized_message

from decimal import Decimal

from fastapi import HTTPException
from tortoise.expressions import Q
from tortoise.functions import Count, Sum

from auth.security import hash_password
from auth.models import User, UserWallet
from models.usage_record import ModelUsageRecord


class UserController:
    async def list_users(
        self, page: int, page_size: int, search: str | None = None
    ) -> dict:
        base = User.all()
        if search and search.strip():
            base = base.filter(
                Q(username__icontains=search.strip())
                | Q(nickname__icontains=search.strip())
            )
        total = await base.count()
        users = await base.order_by("id").offset((page - 1) * page_size).limit(page_size)

        costs = {row['account_user_id']: row['total'] or Decimal('0') for row in
                 await ModelUsageRecord.all().group_by('account_user_id').annotate(total=Sum('cost')).values('account_user_id','total')}
        balances = {row['user_id']: row['balance'] for row in await UserWallet.all().values('user_id','balance')}
        items = [
            {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "is_super_admin": user.is_super_admin,
                "status": user.status,
                "created_at": user.created_at,
                "total_cost": costs.get(user.id, Decimal("0")),
                "balance": balances.get(user.id, Decimal("0")),
            }
            for user in users
        ]
        pages = (total + page_size - 1) // page_size if total else 0
        return {
            "items": items,
            "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
        }

    async def create_user(self, username: str, password: str, nickname: str) -> dict:
        username = username.strip()
        if not username:
            raise HTTPException(status_code=422, detail=localized_message('用户名不能为空'))
        if await User.filter(username=username).exists():
            raise HTTPException(status_code=400, detail=localized_message('用户名已存在'))
        user = await User.create(
            username=username,
            nickname=nickname or username,
            password_hash=hash_password(password),
        )
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "is_super_admin": False,
            "status": user.status,
            "created_at": user.created_at,
            "total_cost": Decimal("0"),
            "balance": Decimal("0"),
        }

    async def set_status(self, user_id: int, status: int, operator_id: int) -> dict:
        if user_id == operator_id:
            raise HTTPException(status_code=400, detail=localized_message('不能修改自己的登录状态'))
        user = await self._get_user(user_id)
        if user.is_super_admin:
            raise HTTPException(status_code=400, detail=localized_message('超级管理员账号不可在界面禁用'))
        user.status = status
        await user.save(update_fields=["status", "updated_at"])
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "is_super_admin": user.is_super_admin,
            "status": user.status,
            "created_at": user.created_at,
            "total_cost": await self._user_total_cost(user.id),
            "balance": (await UserWallet.get_or_create(user_id=user.id))[0].balance,
        }

    async def remove_user(self, user_id: int, operator_id: int) -> None:
        if user_id == operator_id:
            raise HTTPException(status_code=400, detail=localized_message('不能删除自己'))
        user = await self._get_user(user_id)
        if user.is_super_admin:
            raise HTTPException(status_code=400, detail=localized_message('超级管理员账号不可删除'))
        if await UserWallet.filter(user_id=user.id).exclude(balance=0).exists():
            raise HTTPException(400, "用户仍有余额，请先处理余额")
        # Preserve the owner of financial records and revoke access.
        user.status = 0
        await user.save(update_fields=['status', 'updated_at'])

    async def stats(self) -> dict:
        from services.billing.aggregation import summary
        totals = await summary()
        balances = await UserWallet.all().annotate(total=Sum('balance')).values_list('total', flat=True)
        return {'user_count': await User.all().count(), 'user_total_cost': totals['total_cost'],
                'balance_total': sum((Decimal(v or 0) for v in balances), Decimal('0'))}

    async def _get_user(self, user_id: int) -> User:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=localized_message('用户不存在'))
        return user

    async def _user_total_cost(self, user_id: int) -> Decimal:
        total = Decimal("0")
        async for row in ModelUsageRecord.filter(account_user_id=user_id).values("cost"):
            total += Decimal(str(row["cost"] or 0))
        return total


user_controller = UserController()
