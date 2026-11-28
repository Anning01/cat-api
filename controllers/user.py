"""用户管理控制器（仅超级管理员）：列表、统计、禁用登录和删除。"""

from utils.messages import localized_message

from decimal import Decimal
from weakref import WeakSet

from fastapi import HTTPException
from tortoise.expressions import Q, RawSQL, Subquery
from tortoise.functions import Coalesce, Sum
from tortoise.transactions import in_transaction

from auth.security import hash_password
from auth.models import User, UserWallet, UserAdminEvent, QilingIdentity, PlatformApiKey, UserSession
from services.balance import total_consumed


_sqlite_amount_connections = WeakSet()


class _SQLiteConsumed:
    def __init__(self):
        self.total = Decimal(0)

    def step(self, change_amount):
        self.total -= Decimal(change_amount)

    def finalize(self):
        return str(self.total)


async def _user_list_amounts():
    db = User._meta.db
    balance = Coalesce("userwallets__balance", 0)
    cost_sum = "-SUM(change_amount)"
    collation = ""
    if db.capabilities.dialect == "sqlite":
        # SQLite stores DecimalField as text; NUMERIC would lose low digits on large balances.
        # aiosqlite exposes neither registration publicly, so run both on its connection thread.
        async with db.acquire_connection() as connection:
            if connection not in _sqlite_amount_connections:
                await connection._execute(connection._conn.create_aggregate, "cat_consumed", 1, _SQLiteConsumed)
                await connection._execute(connection._conn.create_collation, "cat_decimal",
                                          lambda left, right: int(Decimal(left).compare(Decimal(right))))
                _sqlite_amount_connections.add(connection)
        cost_sum = "cat_consumed(change_amount)"
        collation = " COLLATE cat_decimal"
        balance = RawSQL("COALESCE((SELECT balance FROM userwallet WHERE user_id = users.id), '0')" + collation)
    cost = (f"(SELECT COALESCE({cost_sum}, '0') FROM account_balance_transactions "
            "WHERE account_user_id = users.id AND type = 'consume')")
    return {"balance": balance, "total_cost": RawSQL(cost + collation)}


class UserController:
    async def list_users(self, page: int, page_size: int, search: str | None = None,
                         status: int | None = None, role: str | None = None,
                         balance_view: str | None = None, order_by: str = "-id") -> dict:
        base = User.all()
        if search and search.strip():
            value = search.strip()
            match = Q(username__icontains=value) | Q(nickname__icontains=value)
            if value.isdecimal():
                match |= Q(id=int(value))
            base = base.filter(match)
        if status is not None:
            base = base.filter(status=status)
        if role:
            base = base.filter(is_super_admin=role == "admin")
        if balance_view == "negative":
            base = base.filter(id__in=Subquery(UserWallet.filter(balance__lt=0).values("user_id")))
        elif balance_view == "low":
            base = base.filter(Q(id__in=Subquery(UserWallet.filter(balance__lte=10).values("user_id"))) |
                               ~Q(id__in=Subquery(UserWallet.all().values("user_id"))))
        total = await base.count()
        accounts = base.annotate(**await _user_list_amounts())
        ordering = (order_by,) if order_by in ("id", "-id") else (order_by, "-id")
        users = await accounts.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
        return {"items": [self.user_row(user, Decimal(user.balance), Decimal(user.total_cost)) for user in users],
                "pagination": {"total": total, "page": page, "page_size": page_size,
                               "pages": (total + page_size - 1) // page_size}}

    @staticmethod
    def user_row(user, balance, cost):
        return {"id": user.id, "username": user.username, "nickname": user.nickname,
                "is_super_admin": user.is_super_admin, "status": user.status, "created_at": user.created_at,
                "balance": balance, "total_cost": cost}

    async def detail(self, user_id: int) -> dict:
        user = await self._get_user(user_id)
        wallet = await UserWallet.get_or_none(user_id=user_id)
        session = await UserSession.filter(user_id=user_id, last_seen_at__not_isnull=True).order_by("-last_seen_at").first()
        return {**self.user_row(user, wallet.balance if wallet else Decimal("0"), await self._user_total_cost(user_id)),
                "avatar_url": user.avatar_url,
                "qiling_bound": await QilingIdentity.filter(user_id=user_id).exists(),
                "active_key_count": await PlatformApiKey.filter(user_id=user_id, revoked_at__isnull=True).count(),
                "last_seen_at": session.last_seen_at if session else None}

    async def events(self, user_id: int, page: int, page_size: int) -> dict:
        await self._get_user(user_id)
        query = UserAdminEvent.filter(account_user_id=user_id)
        count = await query.count()
        rows = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size).values()
        operators = {u.id: u.nickname or u.username for u in await User.filter(id__in={r["operator_user_id"] for r in rows})}
        return {"items": [{**row, "operator_name": operators.get(row["operator_user_id"], "#" + str(row["operator_user_id"]))} for row in rows],
                "pagination": {"total": count, "page": page, "page_size": page_size, "pages": (count + page_size - 1) // page_size}}

    async def create_user(self, username: str, password: str, nickname: str, operator_id: int = 0) -> dict:
        username = username.strip()
        if not username:
            raise HTTPException(status_code=422, detail=localized_message('用户名不能为空'))
        if await User.filter(username=username).exists():
            raise HTTPException(status_code=400, detail=localized_message('用户名已存在'))
        async with in_transaction():
            user = await User.create(username=username, nickname=nickname or username, password_hash=hash_password(password))
            await UserAdminEvent.create(account_user_id=user.id, operator_user_id=operator_id, action="create")
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
        async with in_transaction():
            user.status = status
            await user.save(update_fields=["status", "updated_at"])
            await UserAdminEvent.create(account_user_id=user.id, operator_user_id=operator_id, action="enable" if status else "disable")
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
        async with in_transaction():
            user.status = 0
            await user.save(update_fields=['status', 'updated_at'])
            await UserAdminEvent.create(account_user_id=user.id, operator_user_id=operator_id, action='close')

    async def stats(self) -> dict:
        balances = await UserWallet.all().annotate(total=Sum('balance')).values_list('total', flat=True)
        return {'user_count': await User.all().count(), 'user_total_cost': await total_consumed(),
                'balance_total': sum((Decimal(v or 0) for v in balances), Decimal('0'))}

    async def _get_user(self, user_id: int) -> User:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=localized_message('用户不存在'))
        return user

    async def _user_total_cost(self, user_id: int) -> Decimal:
        return await total_consumed(user_id)


user_controller = UserController()
