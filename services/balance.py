"""用户账户余额服务：充值、消费、欠费预检与流水。

策略（D3）：任务提交前预检余额 > 0；任务完成后按计费流水金额原子扣减；
并发下允许透支为负（欠费用户账户在管理端标红，禁止新任务）。
计费/扣减是旁路副作用：消费失败只记日志，绝不打断生成主流程。
"""

from utils.messages import localized_message

import logging
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from auth.models import BalanceTransaction, User, UserWallet
from config import settings

logger = logging.getLogger(__name__)

_CENT = Decimal("0.000001")


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0")


async def wallet(user_id: int):
    if not await User.filter(id=user_id).exists():
        raise HTTPException(404, "用户不存在")
    row, _ = await UserWallet.get_or_create(user_id=user_id)
    return row


async def get_balance(user_id: int) -> Decimal:
    return (await wallet(user_id)).balance


async def ensure_solvent(user_id: int) -> None:
    if await get_balance(user_id) <= 0:
        raise HTTPException(402, "账户余额不足，请充值")


async def top_up(
    user_id: int,
    amount: Decimal,
    operator_user_id: int | None = None,
    note: str = "",
) -> Decimal:
    """超管充值；事务内加锁更新余额并落流水。"""
    amount_dec = _money(amount)
    if amount_dec <= 0:
        raise HTTPException(status_code=400, detail=localized_message('充值金额必须为正数'))
    async with in_transaction():
        await wallet(user_id)
        account = await UserWallet.filter(user_id=user_id).select_for_update().get()
        if account is None:
            raise HTTPException(status_code=404, detail=localized_message('用户账户不存在'))
        account.balance = _money(account.balance + amount_dec)
        await account.save(update_fields=["balance", "updated_at"])
        await BalanceTransaction.create(
            account_user_id=user_id,
            change_amount=amount_dec,
            balance_after=account.balance,
            type="topup",
            operator_user_id=operator_user_id,
            note=note or "余额充值",
        )
    return account.balance


async def consume(
    user_id: int,
    cost,
    usage_record_id: int | None = None,
    *, strict: bool = False,
) -> Decimal | None:
    """任务完成后按实际成本扣减；允许透支为负。失败仅记日志，不抛异常。"""
    try:
        cost_dec = _money(cost)
        if cost_dec <= 0:
            return None
        async with in_transaction():
            await wallet(user_id)
            account = await UserWallet.filter(user_id=user_id).select_for_update().get()
            if account is None:
                if strict:
                    raise ValueError('Billing account is unavailable')
                return None
            account.balance = _money(account.balance - cost_dec)
            await account.save(update_fields=["balance", "updated_at"])
            await BalanceTransaction.create(
                account_user_id=user_id,
                change_amount=-cost_dec,
                balance_after=account.balance,
                type="consume",
                usage_record_id=usage_record_id,
                note="AI 调用扣费",
            )
        return account.balance
    except Exception:
        if strict:
            raise
        logger.exception("balance consume failed user_id=%s", user_id)
        return None


async def list_transactions(
    user_id: int, page: int, page_size: int
) -> dict:
    """用户账户余额流水（分页，倒序）。"""
    query = BalanceTransaction.filter(account_user_id=user_id)
    total = await query.count()
    items = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": items,
        "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
    }
