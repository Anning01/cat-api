"""Personal balance and recharge API contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from schemas._base import BaseModelWithTime, BaseResponse
from utils.response_format import PaginationResponse


def _serialize_decimal(value: Decimal) -> str:
    """Decimal 统一以定点字符串序列化（避免 1E+2 科学计数法）。"""
    return format(value, "f")


class AccountBalanceOut(BaseModel):
    account_user_id: int = Field(..., description="用户 ID")
    balance: Decimal = Field(..., description="当前余额（元）")

    @field_serializer("balance", when_used="json")
    def _ser_balance(self, value: Decimal) -> str:
        return _serialize_decimal(value)


class BalanceTopUpIn(BaseModel):
    account_user_id: int = Field(..., gt=0, description="目标用户")
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2, description="充值金额（元）")
    note: str = Field("", max_length=255, description="备注")


class RechargeCreateIn(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2, description="充值金额（元）")
    note: str = Field("", max_length=255, description="充值备注")


class RechargeOrderOut(BaseModelWithTime):
    model_config = ConfigDict(from_attributes=True)

    id: int
    out_trade_no: str
    account_user_id: int
    amount: Decimal
    status: str
    payment_method: str
    code_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @field_serializer("amount", when_used="json")
    def _ser_amount(self, value: Decimal) -> str:
        return _serialize_decimal(value)


class RechargeOrderDetailOut(RechargeOrderOut):
    transaction_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    balance_after: Optional[Decimal] = None
    refund_id: Optional[str] = None
    refunded_at: Optional[datetime] = None
    refund_reason: str = ""
    note: str = ""

    @field_serializer("balance_after", when_used="json")
    def _ser_bal(self, value: Optional[Decimal]) -> Optional[str]:
        return _serialize_decimal(value) if value is not None else None


class RechargeOrderAdminOut(BaseModel):
    """充值订单管理列表项（支持超管与普通用户）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    out_trade_no: str
    account_user_id: int
    user_id: int
    username: str = ""
    nickname: str = ""
    amount: Decimal
    status: str
    payment_method: str = "wechat_native"
    code_url: Optional[str] = None
    transaction_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    note: str = ""
    refund_id: Optional[str] = None
    refunded_at: Optional[datetime] = None
    refund_reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_serializer("amount", when_used="json")
    def _ser_amount(self, value: Decimal) -> str:
        return _serialize_decimal(value)


class RefundOrderIn(BaseModel):
    reason: str = Field("", max_length=255, description="退款原因或备注说明")


class BalanceTransactionOut(BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_user_id: int
    change_amount: Decimal
    balance_after: Decimal
    type: str
    usage_record_id: int | None = None
    operator_user_id: int | None = None
    note: str = ""

    @field_serializer("change_amount", "balance_after", when_used="json")
    def _ser_amounts(self, value: Decimal) -> str:
        return _serialize_decimal(value)
