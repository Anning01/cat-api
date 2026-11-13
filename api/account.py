"""Personal balances and payment orders."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from datetime import date
from auth.deps import AuthContext, get_auth_context, require_super_admin
from controllers.account import account_controller
from schemas.account import (AccountBalanceOut, BalanceTopUpIn, RechargeCreateIn, RechargeOrderOut,
    RechargeOrderDetailOut, RechargeOrderAdminOut, RefundOrderIn, BalanceTransactionOut)
from utils.page import get_list_params
from utils.response_format import ResponseSchema, PaginationResponse

router = APIRouter()


def owner(ctx: AuthContext = Depends(get_auth_context)):
    if not ctx.user:
        raise HTTPException(401, "需要登录")
    return ctx


@router.get('/balance', response_model=ResponseSchema[AccountBalanceOut])
async def balance(ctx=Depends(owner)):
    return ResponseSchema(data=await account_controller.balance(ctx.user.id))


@router.post('/balance/topup', response_model=ResponseSchema[AccountBalanceOut])
async def topup(payload: BalanceTopUpIn, ctx=Depends(require_super_admin)):
    return ResponseSchema(data=await account_controller.top_up(payload.account_user_id, payload.amount, ctx.user.id, payload.note))


@router.get('/balance/transactions', response_model=ResponseSchema[PaginationResponse[BalanceTransactionOut]])
async def transactions(ctx=Depends(owner), params=Depends(get_list_params)):
    return ResponseSchema(data=await account_controller.transactions(ctx.user.id, params.page, params.page_size))


@router.post('/recharge', response_model=ResponseSchema[RechargeOrderOut])
async def recharge(payload: RechargeCreateIn, ctx=Depends(owner)):
    return ResponseSchema(data=await account_controller.create_recharge(ctx.user.id, payload.amount, payload.note))


@router.get('/recharge/{out_trade_no}', response_model=ResponseSchema[RechargeOrderDetailOut])
async def recharge_status(out_trade_no: str, ctx=Depends(owner)):
    order, current = await account_controller.query_recharge(out_trade_no, ctx.user.id, ctx.is_super_admin)
    data = RechargeOrderDetailOut.model_validate(order)
    data.balance_after = current
    return ResponseSchema(data=data)


@router.get('/orders', response_model=ResponseSchema[PaginationResponse[RechargeOrderAdminOut]])
async def orders(background_tasks: BackgroundTasks, status: str | None = None, search: str | None = None,
                 account_user_id: int | None = None, start_date: date | None = None, end_date: date | None = None,
                 ctx=Depends(owner), params=Depends(get_list_params)):
    if ctx.is_super_admin:
        background_tasks.add_task(account_controller.cleanup_recharge_orders)
    return ResponseSchema(data=await account_controller.list_orders(ctx.user.id, ctx.is_super_admin,
        status, search, params.page, params.page_size, account_user_id, start_date, end_date))


@router.post('/orders/{out_trade_no}/refund', response_model=ResponseSchema[RechargeOrderOut])
async def refund(out_trade_no: str, payload: RefundOrderIn, ctx=Depends(require_super_admin)):
    return ResponseSchema(data=await account_controller.refund_recharge(out_trade_no, ctx.user.id, payload.reason))
