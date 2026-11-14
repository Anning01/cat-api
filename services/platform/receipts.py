from fastapi import HTTPException

from auth.models import PlatformCallReceipt
from models.usage_record import ModelUsageRecord
from schemas.platform_billing import PlatformReceiptOut, PlatformSettlement
from services.platform.catalog import public_tariff
from services.platform.calls import request_keys
from services.platform.access import authorize_model


async def call_receipt(request_id, ctx, *, by_key=False) -> PlatformReceiptOut:
    identity = {"dedup_key__in": await request_keys(ctx.user.id, request_id)} if by_key else {"public_id": request_id}
    rows = await PlatformCallReceipt.filter(**identity, user_id=ctx.user.id).limit(2)
    if len(rows) > 1:
        raise HTTPException(409, "旧请求标识对应多条记录，请使用原请求编号查询")
    row = rows[0] if rows else None
    if row is None:
        raise HTTPException(404, "请求不存在")
    authorize_model(ctx, row.model_config_id)
    settlement = PlatformSettlement(status="review" if row.state == "review" else
        "not_charged" if row.state == "rejected" else "pending")
    if row.state == "completed" and row.usage_record_id is not None:
        record = await ModelUsageRecord.get_or_none(id=row.usage_record_id, user_id=row.user_id)
        if record is not None:
            settlement = PlatformSettlement(status="settled", amount=record.cost, currency=record.currency)
    from models.config import AiModelConfig
    config = await AiModelConfig.get_or_none(id=row.model_config_id)
    return PlatformReceiptOut(model_alias=config.public_alias if config else None, model_name=row.model_name, id=row.public_id, model=f"nv-{row.model_config_id}", status=row.state,
        usage=row.usage, settlement=settlement, pricing=public_tariff(row.pricing))
