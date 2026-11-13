"""账单聚合：总览、项目成本、项目明细、流水分页。"""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from config import settings
from models.usage_record import ModelUsageRecord


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _money(value: Decimal) -> float:
    return round(float(value), 6)


async def summary(
    novel_id: int | None = None,
    team_id: int | None = None,
    user_id: int | None = None,
    *, cost_source: str | None = None, recent_days: int | None = None,
) -> dict:
    query = ModelUsageRecord.all()
    if cost_source is not None:
        query = query.filter(cost_source=cost_source)
    if novel_id is not None:
        query = query.filter(novel_id=novel_id)
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    days = []
    if recent_days is not None:
        end = datetime.now(settings.tz).date() + timedelta(days=1)
        start = end - timedelta(days=recent_days)
        query = query.filter(
            created_at__gte=datetime.combine(start, time.min, settings.tz).astimezone(timezone.utc),
            created_at__lt=datetime.combine(end, time.min, settings.tz).astimezone(timezone.utc),
        )
        days = [(start + timedelta(days=offset)).isoformat() for offset in range(recent_days)]
    rows = await query.values(
        "task_type", "billing_type", "model", "model_name", "cost", "created_at", "platform_cost", "local_charge", "settlement_status"
    )
    total = sum((_dec(row["cost"]) for row in rows), Decimal("0"))
    by_billing: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_task: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    by_model: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    model_records: Counter[str] = Counter()
    daily: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        cost = _dec(row["cost"])
        by_billing[row["billing_type"]] += cost
        by_task[row["task_type"]] += cost
        model = row["model_name"] or row["model"] or "未知模型"
        by_model[model] += cost
        model_records[model] += 1
        created_at = row["created_at"]
        if recent_days is not None:
            created_at = created_at.astimezone(settings.tz)
        daily[created_at.date().isoformat()] += cost
    return {
        "total_cost": _money(total),
        "total_records": len(rows),
        "platform_cost": _money(sum((_dec(row["platform_cost"]) for row in rows), Decimal("0"))),
        "local_charge": _money(sum((_dec(row["local_charge"]) for row in rows), Decimal("0"))),
        "pending_records": sum(row["settlement_status"] in {"pending", "review"} for row in rows),
        "by_billing_type": [
            {"billing_type": key, "cost": _money(value)}
            for key, value in sorted(by_billing.items())
        ],
        "by_task_type": [
            {"task_type": key, "cost": _money(value)}
            for key, value in sorted(by_task.items())
        ],
        "by_model": [
            {"model": key, "cost": _money(value), "record_count": model_records[key]}
            for key, value in sorted(by_model.items(), key=lambda item: -item[1])
        ],
        "daily_trend": [
            {"date": day, "cost": _money(daily[day])}
            for day in (days or sorted(daily))
        ],
    }
