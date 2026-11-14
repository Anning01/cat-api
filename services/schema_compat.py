from tortoise import Tortoise
from config import settings

async def ensure_admin_events_schema() -> None:
    connection = Tortoise.get_connection("default")
    sqlite = connection.capabilities.dialect == "sqlite"
    identity = "INTEGER PRIMARY KEY AUTOINCREMENT" if sqlite else "SERIAL PRIMARY KEY"
    timestamp = "TIMESTAMP" if sqlite else "TIMESTAMPTZ"
    await connection.execute_script(f"""
        CREATE TABLE IF NOT EXISTS account_admin_events (
            id {identity}, account_user_id INT NOT NULL, operator_user_id INT NOT NULL,
            action VARCHAR(32) NOT NULL, note VARCHAR(255) NOT NULL DEFAULT '',
            created_at {timestamp} NOT NULL, updated_at {timestamp} NOT NULL
        );
        CREATE INDEX IF NOT EXISTS account_admin_events_user_idx ON account_admin_events(account_user_id);
    """)

async def ensure_billing_integration_schema() -> None:
    """Add platform accounting fields while preserving historical records."""
    connection = Tortoise.get_connection("default")
    definitions = {
        "ai_model_configs": {"public_alias":"VARCHAR(200)"},
        "general_configs": {"api_docs_url":"VARCHAR(2048)"},
        "model_usage_records": {
            "account_user_id": "INT",
            "platform_cost": "DECIMAL(18,6)",
            "local_charge": "DECIMAL(18,6)",
            "settlement_status": "VARCHAR(16) NOT NULL DEFAULT 'legacy'",
        },
        "platformcallreceipt": {"api_key_id": "INT"},
        "account_api_keys": {
            "encrypted_token": "TEXT",
            "allowed_model_ids": "JSON" if connection.capabilities.dialect == "sqlite" else "JSONB",
            "expires_at": "TIMESTAMP" if connection.capabilities.dialect == "sqlite" else "TIMESTAMPTZ",
        },
    }
    for table, columns in definitions.items():
        if connection.capabilities.dialect == "sqlite":
            existing = await connection.execute_query_dict(f"PRAGMA table_info({table})")
            if not existing:
                continue
            names = {row["name"] for row in existing}
            for name, definition in columns.items():
                if name not in names:
                    await connection.execute_script(f"ALTER TABLE {table} ADD COLUMN {name} {definition};")
        else:
            for name, definition in columns.items():
                await connection.execute_script(f"ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS {name} {definition};")

async def _ensure_qiling_issuer_columns(connection) -> None:
    # An older development schema did not record the issuer. An empty value
    # keeps old attempts and identities from being trusted under a new issuer.
    for table in ("qiling_identities", "qiling_login_attempts"):
        if settings.DATABASE_URL.startswith("sqlite"):
            columns = await connection.execute_query_dict(f"PRAGMA table_info({table})")
            if columns and "issuer" not in {column["name"] for column in columns}:
                await connection.execute_script(f"ALTER TABLE {table} ADD COLUMN issuer VARCHAR(255) NOT NULL DEFAULT '';")
        elif settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
            await connection.execute_script(
                f"ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS issuer VARCHAR(255) NOT NULL DEFAULT '';"
            )


async def ensure_recharge_refund_columns() -> None:
    if not settings.AUTH_ENABLED:
        return
    connection = Tortoise.get_connection("default")
    if settings.DATABASE_URL.startswith("sqlite"):
        columns = await connection.execute_query_dict("PRAGMA table_info(recharge_orders)")
        if not columns:
            return
        col_names = {row["name"] for row in columns}
        if "refund_id" not in col_names:
            await connection.execute_script("ALTER TABLE recharge_orders ADD COLUMN refund_id VARCHAR(128);")
        if "refunded_at" not in col_names:
            await connection.execute_script("ALTER TABLE recharge_orders ADD COLUMN refunded_at TIMESTAMP;")
        if "refund_reason" not in col_names:
            await connection.execute_script("ALTER TABLE recharge_orders ADD COLUMN refund_reason VARCHAR(255) DEFAULT '';")
    elif settings.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        await connection.execute_script(
            "ALTER TABLE IF EXISTS recharge_orders ADD COLUMN IF NOT EXISTS refund_id VARCHAR(128);"
            "ALTER TABLE IF EXISTS recharge_orders ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMP WITH TIME ZONE;"
            "ALTER TABLE IF EXISTS recharge_orders ADD COLUMN IF NOT EXISTS refund_reason VARCHAR(255) DEFAULT '';"
        )
