"""Import legacy account data once; leave all source tables untouched."""
from decimal import Decimal

from tortoise import Tortoise, fields
from tortoise.transactions import in_transaction

from auth.models import (AccountMigration, BalanceTransaction, PlatformApiKey, PlatformCallReceipt,
    PlatformVideoJob, RechargeOrder, StudioKeyGrant, StudioMediaLease, User, UserWallet)

MIGRATION = 'individual-accounts-v1'
SOURCES = (
    (BalanceTransaction, 'balance_transactions'), (RechargeOrder, 'recharge_orders'),
    (PlatformApiKey, 'platformapikey'), (PlatformCallReceipt, 'platformcallreceipt'),
    (StudioKeyGrant, 'studiokeygrant'), (StudioMediaLease, 'studiomedialease'),
    (PlatformVideoJob, 'platformvideojob'),
)


async def table_exists(db, name):
    if db.capabilities.dialect == 'sqlite':
        return bool(await db.execute_query_dict('SELECT name FROM sqlite_master WHERE type=\'table\' AND name=?', [name]))
    return bool((await db.execute_query_dict('SELECT to_regclass($1) AS name', [name]))[0]['name'])


async def migrate_user_accounts():
    async with in_transaction() as db:
        if db.capabilities.dialect == 'postgres':
            await db.execute_query("SELECT pg_advisory_xact_lock(81313001)")
        if await AccountMigration.filter(name=MIGRATION).using_db(db).exists():
            return
        owners = {}
        totals = {}
        if await table_exists(db, 'teams'):
            users = set(await User.all().using_db(db).values_list('id', flat=True))
            for row in await db.execute_query_dict('SELECT id, owner_user_id, balance FROM teams ORDER BY id'):
                owner = row['owner_user_id']
                if owner not in users:
                    raise ValueError('Legacy balance owner is missing; migration requires review')
                owners[row['id']] = owner
                totals[owner] = totals.get(owner, Decimal('0')) + Decimal(str(row['balance']))
        # No credits may be duplicated into a previously active destination.
        if await UserWallet.all().using_db(db).exists():
            raise ValueError('Destination wallets already exist without a migration marker')
        for user_id, amount in totals.items():
            await UserWallet.create(using_db=db, user_id=user_id, balance=amount)
        for model, source in SOURCES:
            if not await table_exists(db, source):
                continue
            if await model.all().using_db(db).exists():
                raise ValueError('Destination contains records without a migration marker')
            for row in await db.execute_query_dict(f'SELECT * FROM "{source}" ORDER BY id'):
                data = {}
                for name, column in model._meta.fields_db_projection.items():
                    if column not in row:
                        continue
                    value = row[column]
                    field = model._meta.fields_map[name]
                    data[column] = field.to_python_value(value)
                if 'account_user_id' in model._meta.fields_map:
                    data['account_user_id'] = owners.get(row.get('team_id'), row.get('user_id'))
                    if data['account_user_id'] is None:
                        raise ValueError('Legacy record has no account owner')
                if model is PlatformCallReceipt:
                    data['legacy_scope_id'] = row['team_id']
                await model.bulk_create([model(**data)], using_db=db)
            if db.capabilities.dialect == 'postgres':
                table = model._meta.db_table
                await db.execute_query(f"SELECT setval(pg_get_serial_sequence('{table}','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM {table}")
        # Historical usage keeps its actor; the wallet owner is independent.
        if owners and await table_exists(db, 'model_usage_records'):
            for scope_id, owner in owners.items():
                marker = '?' if db.capabilities.dialect == 'sqlite' else '$1'
                second = '?' if db.capabilities.dialect == 'sqlite' else '$2'
                await db.execute_query(f'UPDATE model_usage_records SET account_user_id={marker} WHERE team_id={second}', [owner, scope_id])
        await AccountMigration.create(using_db=db, name=MIGRATION)
