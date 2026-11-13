from decimal import Decimal

from auth.models import BalanceTransaction, UserWallet, User
from models.usage_record import ModelUsageRecord
from schemas.billing import StatementFilters
from services.billing.statements import billing_statements


async def test_actual_deductions_are_scoped_and_exportable():
    user = await User.create(username='ledger-user')
    wallet = await UserWallet.create(user=user, balance=Decimal('9.876544'))
    other = await User.create(username='other')
    usage = await ModelUsageRecord.create(novel_id=0, task_type=1, billing_type='text',
        model='test', user_id=user.id, account_user_id=user.id, usage={'input_tokens': 7, 'secret': 'hidden'})
    await BalanceTransaction.create(account_user_id=user.id, type='consume', change_amount=Decimal('-0.123456'),
        balance_after=wallet.balance, usage_record_id=usage.id)
    await BalanceTransaction.create(account_user_id=other.id, type='consume', change_amount=-2, balance_after=0)
    await BalanceTransaction.create(account_user_id=user.id, type='topup', change_amount=10, balance_after=10)
    filters = StatementFilters(account_user_id=user.id, user_id=user.id)
    result = await billing_statements.list(filters, 1, 20)
    assert result['summary'] == {'total_cost': '0.123456', 'total_transactions': 1, 'account_balance': '9.876544'}
    assert result['items'][0].usage == {'input_tokens': 7}
    exported = ''.join([chunk async for chunk in billing_statements.export(filters)])
    assert '0.123456' in exported and 'hidden' not in exported
    assert await UserWallet.get(user_id=user.id).values_list('balance', flat=True) == Decimal('9.876544')


async def test_expiration_cleans_only_old_invalid_orders():
    from datetime import timedelta
    from auth.models import RechargeOrder
    from controllers.account import account_controller
    from tortoise.timezone import now as tz_now

    user = await User.create(username='orders')
    for status in ('expired', 'closed', 'failed', 'paid', 'pending'):
        order = await RechargeOrder.create(account_user_id=user.id, user_id=1, amount=10,
            out_trade_no=status, status=status, expires_at=tz_now() - timedelta(days=10))
        await RechargeOrder.filter(id=order.id).update(created_at=tz_now() - timedelta(days=10))
    await RechargeOrder.create(account_user_id=user.id, user_id=1, amount=10, out_trade_no='recent', status='expired')
    await account_controller.cleanup_recharge_orders()
    assert await RechargeOrder.all().count() == 2
    assert await RechargeOrder.filter(out_trade_no='recent').exists()
    assert await RechargeOrder.get(out_trade_no='paid').values_list('status', flat=True) == 'paid'


async def test_statement_routes_require_super_admin():
    from httpx import ASGITransport, AsyncClient
    from auth.deps import AuthContext, get_auth_context
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/billing/statements')).json()['code'] == 401
        app.dependency_overrides[get_auth_context] = lambda: AuthContext()
        try:
            assert (await client.get('/api/billing/statements')).json()['code'] == 403
            app.dependency_overrides[get_auth_context] = lambda: AuthContext(is_super_admin=True)
            result = await client.get('/api/billing/statements')
            assert result.status_code == 200 and result.json()['data']['summary']['total_cost'] == '0.000000'
            assert (await client.get('/api/billing/statements?start_date=2026-11-13&end_date=2026-11-01')).json()['code'] == 422
        finally:
            app.dependency_overrides.clear()
