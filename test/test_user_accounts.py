from decimal import Decimal
from datetime import timedelta

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise
from tortoise.timezone import now

from auth.deps import AuthContext
from auth.models import BalanceTransaction, PlatformApiKey, RechargeOrder, User, UserWallet
from controllers.account import account_controller
from services.balance import consume, top_up
from services.migrations.user_accounts import migrate_user_accounts
from services.platform.access import create_key


async def legacy_fixture(owner_id):
    db = Tortoise.get_connection('default')
    await db.execute_script(f'''
        ALTER TABLE model_usage_records ADD COLUMN team_id INT;
        CREATE TABLE teams (id INTEGER PRIMARY KEY, owner_user_id INT, balance DECIMAL(18,6));
        INSERT INTO teams VALUES (40,{owner_id},12.123456), (41,{owner_id},-2.000001);
        CREATE TABLE balance_transactions (id INTEGER PRIMARY KEY, team_id INT,
            change_amount DECIMAL(18,6), balance_after DECIMAL(18,6), type TEXT,
            usage_record_id INT, operator_user_id INT, note TEXT, created_at TIMESTAMP, updated_at TIMESTAMP);
        INSERT INTO balance_transactions VALUES (8,40,12.123456,12.123456,'topup',NULL,{owner_id},'old',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
        INSERT INTO balance_transactions VALUES (9,41,-2.000001,-2.000001,'consume',NULL,{owner_id},'old',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
    ''')


async def test_migration_merges_balances_once_preserves_history_and_new_deductions():
    user = await User.create(username='owner')
    await legacy_fixture(user.id)
    await migrate_user_accounts()
    assert await UserWallet.get(user_id=user.id).values_list('balance', flat=True) == Decimal('10.123455')
    assert await BalanceTransaction.filter(account_user_id=user.id).count() == 2
    await consume(user.id, Decimal('0.123455'), strict=True)
    await migrate_user_accounts()
    assert await UserWallet.get(user_id=user.id).values_list('balance', flat=True) == Decimal('10')
    assert await BalanceTransaction.all().count() == 3
    old = await Tortoise.get_connection('default').execute_query_dict('SELECT COUNT(*) AS n FROM balance_transactions')
    assert old[0]['n'] == 2


async def test_migration_missing_owner_aborts_without_credits():
    await legacy_fixture(99999)
    with pytest.raises(ValueError, match='owner is missing'):
        await migrate_user_accounts()
    assert not await UserWallet.all().exists()
    assert not await BalanceTransaction.all().exists()


async def test_user_balance_and_key_ignore_old_team_header():
    from main import app
    from auth.models import UserSession
    from auth.security import hash_token
    user = await User.create(username='personal')
    other = await User.create(username='other')
    await top_up(user.id, Decimal('5.25'))
    await top_up(other.id, Decimal('20'))
    await UserSession.create(user=user, token_hash=hash_token('session-fixture'), expires_at=now()+timedelta(hours=1))
    key = await create_key(AuthContext(user=user), 'personal')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/v1/account', headers={'Authorization': 'Bearer '+key['key'], 'X-Team-Id': str(other.id)})
        assert response.status_code == 200 and Decimal(response.json()['balance']) == Decimal('5.25')
        headers = {'Authorization':'Bearer session-fixture', 'X-Team-Id':str(other.id)}
        me = (await client.get('/api/auth/me', headers=headers)).json()['data']
        assert Decimal(me['balance']) == Decimal('5.25') and 'memberships' not in me
        assert (await client.get('/api/team/members', headers=headers)).json()['code'] == 404
    await consume(user.id, Decimal('1.25'), strict=True)
    assert await UserWallet.get(user_id=other.id).values_list('balance', flat=True) == Decimal('20')
    assert await PlatformApiKey.filter(user_id=user.id).count() == 1


async def test_payment_settles_user_once_and_refund_reservation_is_durable(monkeypatch):
    from services.recharge_refunds import recharge_refunds
    from services.wechat_pay import wechat_pay_service
    user = await User.create(username='payment')
    order = await RechargeOrder.create(user_id=user.id, account_user_id=user.id, out_trade_no='test-order', amount=10)
    assert await account_controller._finish_recharge(order, 'provider-id') is True
    assert await account_controller._finish_recharge(order, 'provider-id') is False
    assert await UserWallet.get(user_id=user.id).values_list('balance', flat=True) == Decimal('10')
    async def processing(**kwargs):
        return {'status':'PROCESSING', 'refund_id':'refund-fixture'}
    monkeypatch.setattr(wechat_pay_service, 'create_refund', processing)
    await recharge_refunds.request(order.out_trade_no, user.id, 'requested')
    await recharge_refunds.request(order.out_trade_no, user.id, 'requested')
    assert await UserWallet.get(user_id=user.id).values_list('balance', flat=True) == Decimal('0')
    await recharge_refunds.settle(order, {'status':'CLOSED'})
    await recharge_refunds.settle(order, {'status':'CLOSED'})
    assert await UserWallet.get(user_id=user.id).values_list('balance', flat=True) == Decimal('10')
    assert await BalanceTransaction.all().count() == 3


async def test_historical_member_key_and_late_settlement_keep_original_payer():
    from uuid import uuid4
    from auth.security import hash_token
    from auth.models import PlatformCallReceipt
    from models.config import AiModelConfig
    from models.usage_record import ModelUsageRecord
    from services.platform.calls import digest, settle
    from services.platform.receipts import call_receipt
    owner = await User.create(username='old-owner')
    actor = await User.create(username='old-member')
    await legacy_fixture(owner.id)
    config = await AiModelConfig.create(task_type=7,name='legacy',model='fixture',base_url='https://example.test',
        api_key='fixture',pricing={'type':'text','input_price_per_1m':1,'output_price_per_1m':2})
    db = Tortoise.get_connection('default')
    await db.execute_script('''CREATE TABLE platformapikey (id INTEGER PRIMARY KEY,user_id INT,team_id INT,name TEXT,
        token_hash TEXT,preview TEXT,revoked_at TIMESTAMP,created_at TIMESTAMP,updated_at TIMESTAMP);
        CREATE TABLE platformcallreceipt (id INTEGER PRIMARY KEY,public_id TEXT,dedup_key TEXT,payload_hash TEXT,
        team_id INT,user_id INT,api_key_id INT,model_config_id INT,model_name TEXT,model TEXT,pricing TEXT,state TEXT,
        provider_id TEXT,usage TEXT,usage_record_id INT,created_at TIMESTAMP,updated_at TIMESTAMP);''')
    import json
    await db.execute_query('INSERT INTO platformapikey VALUES(1,?,40,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)',
        [actor.id,'old-key',hash_token('nv_old_fixture'),'nv_old',None])
    public_id = str(uuid4())
    await db.execute_query('INSERT INTO platformcallreceipt VALUES(1,?,?,?,40,?,1,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)',
        [public_id,digest([40,actor.id,'original-request']),'signature',actor.id,config.id,'legacy','fixture',
         json.dumps(config.pricing),'measured','upstream',json.dumps({'input_tokens':10,'output_tokens':2}),None])
    await migrate_user_accounts()
    key = await PlatformApiKey.get(id=1)
    assert key.user_id == actor.id and key.token_hash == hash_token('nv_old_fixture')
    recovered = await call_receipt('original-request',AuthContext(user=actor),by_key=True)
    assert str(recovered.id) == public_id
    await settle(1)
    await settle(1)
    record = await ModelUsageRecord.get(user_id=actor.id)
    assert record.account_user_id == owner.id and record.cost == Decimal('0.000014')
    assert await UserWallet.get(user_id=owner.id).values_list('balance',flat=True) == Decimal('10.123441')
    assert not await UserWallet.filter(user_id=actor.id).exists()
