"""Explicit database preparation; rolling instances may start without DDL."""
from tortoise import Tortoise
from config import settings
from auth.bootstrap import ensure_super_admin
from services.schema_compat import (
    _ensure_qiling_issuer_columns, ensure_billing_integration_schema, ensure_recharge_refund_columns,
)


async def initialize_database():
    from services.schema_compat import ensure_admin_events_schema
    await ensure_admin_events_schema()
    await ensure_billing_integration_schema()
    from services.schema_compat import ensure_model_reasoning_schema
    await ensure_model_reasoning_schema()
    await _ensure_qiling_issuer_columns(Tortoise.get_connection("default"))
    await ensure_recharge_refund_columns()
    if settings.GENERATE_SCHEMAS:
        await Tortoise.generate_schemas(safe=True)
    from services.video.ark_migration import migrate_legacy_video_channels
    await migrate_legacy_video_channels()
    from services.migrations.user_accounts import migrate_user_accounts
    await migrate_user_accounts()
    from services.platform.model_aliases import ensure_model_aliases
    await ensure_model_aliases()
    await ensure_super_admin()


async def check_database_schema():
    """Resolve every mapped column without loading data or changing the schema."""
    db = Tortoise.get_connection("default")
    for model in Tortoise.apps["models"].values():
        columns = ", ".join('"mapped"."'+name+'"' for name in model._meta.fields_db_projection.values())
        await db.execute_query(f'SELECT {columns} FROM "{model._meta.db_table}" AS "mapped" LIMIT 0')
