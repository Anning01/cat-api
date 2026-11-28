from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from auth.deps import AuthContext, get_auth_context
from auth.models import BalanceTransaction, RechargeOrder, User, UserWallet, UserAdminEvent
from controllers.account import account_controller
from controllers.user import user_controller


async def test_user_filters_apply_before_pagination_and_include_unfunded_accounts():
    admin = await User.create(username='admin', is_super_admin=True)
    low = await User.create(username='low')
    debt = await User.create(username='debt', status=0)
    await UserWallet.create(user=admin, balance=100)
    await UserWallet.create(user=debt, balance=Decimal('-0.000001'))
    result = await user_controller.list_users(1, 1, role='user', balance_view='low')
    assert result['pagination']['total'] == 2
    assert len(result['items']) == 1
    result = await user_controller.list_users(1, 20, status=0, balance_view='negative')
    assert [row['id'] for row in result['items']] == [debt.id]
    assert result['items'][0]['balance'] == Decimal('-0.000001')
    result = await user_controller.list_users(1, 20, search=str(low.id))
    assert [row['id'] for row in result['items']] == [low.id]


async def test_user_list_sorts_filtered_accounts_by_amount_across_pages(monkeypatch):
    from main import app

    admin = await User.create(username='admin', is_super_admin=True)
    high = await User.create(username='high-balance')
    unfunded = await User.create(username='unfunded')
    spender = await User.create(username='split-spend')
    debt = await User.create(username='debt')
    empty = await User.create(username='empty-wallet')
    highest = await User.create(username='highest-balance')
    await User.create(username='disabled', status=0)
    balances = {
        high.id: Decimal('987654321000.000001'), highest.id: Decimal('987654321000.000002'),
        spender.id: 2, debt.id: Decimal('-0.000001'), empty.id: 0,
    }
    for user_id, balance in balances.items():
        await UserWallet.create(user_id=user_id, balance=balance)
    for user, kind, amount in [
        (spender, 'consume', '-0.1'), (spender, 'consume', '-0.2'),
        (debt, 'consume', '-0.3'), (high, 'topup', '100'),
        (high, 'consume', '-987654321000.000002'), (highest, 'consume', '-987654321000.000001'),
    ]:
        await BalanceTransaction.create(
            account_user_id=user.id, type=kind, change_amount=Decimal(amount), balance_after=0,
        )

    monkeypatch.setitem(app.dependency_overrides, get_auth_context, lambda: AuthContext(user=admin, is_super_admin=True))
    costs = {
        high.id: Decimal('987654321000.000002'), highest.id: Decimal('987654321000.000001'),
        spender.id: Decimal('0.3'), debt.id: Decimal('0.3'),
    }
    expected_orders = {
        'balance': [debt, empty, unfunded, spender, high, highest],
        '-balance': [highest, high, spender, empty, unfunded, debt],
        'total_cost': [empty, unfunded, debt, spender, highest, high],
        '-total_cost': [high, highest, debt, spender, empty, unfunded],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for order_by, expected in expected_orders.items():
            for page in range(1, 4):
                result = (await client.get('/api/users', params={
                    'role': 'user', 'status': 1, 'order_by': order_by, 'page_size': 2, 'page': page,
                })).json()
                assert result['code'] == 0, result
                data = result['data']
                assert data['pagination']['total'] == len(expected)
                expected_page = expected[(page - 1) * 2:page * 2]
                assert [row['id'] for row in data['items']] == [user.id for user in expected_page]
                for row in data['items']:
                    assert Decimal(row['balance']) == balances.get(row['id'], 0)
                    assert row['total_cost'] == float(costs.get(row['id'], 0))

    result = await user_controller.list_users(1, 20, status=1, role='user', order_by='-total_cost')
    for row in result['items']:
        assert row['total_cost'] == costs.get(row['id'], 0)


async def test_user_admin_actions_are_audited_without_credentials():
    operator = await User.create(username='operator', is_super_admin=True)
    row = await user_controller.create_user('new-user', 'password-fixture', 'New', operator.id)
    await account_controller.top_up(row['id'], Decimal('10.25'), operator.id, 'Support adjustment')
    await user_controller.set_status(row['id'], 0, operator.id)
    history = await user_controller.events(row['id'], 1, 20)
    assert [event['action'] for event in history['items']] == ['disable', 'topup', 'create']
    assert all(event['operator_name'] == 'operator' for event in history['items'])
    assert 'password-fixture' not in str(history)
    detail = await user_controller.detail(row['id'])
    assert detail['balance'] == Decimal('10.25')
    assert not {'password_hash', 'token_hash', 'unionid', 'openid'} & detail.keys()
    before = await UserAdminEvent.all().count()
    with pytest.raises(Exception):
        await account_controller.top_up(999999, Decimal('1'), operator.id, 'Invalid account')
    assert await UserAdminEvent.all().count() == before


async def test_admin_routes_and_personal_ledger_do_not_cross_account_boundaries():
    from main import app
    user = await User.create(username='viewer')
    other = await User.create(username='other-viewer')
    await BalanceTransaction.create(account_user_id=user.id, type='consume', change_amount=Decimal('-.123456'), balance_after=1)
    await BalanceTransaction.create(account_user_id=other.id, type='consume', change_amount=-50, balance_after=100)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            for path in [f'/api/users/{other.id}', f'/api/users/{other.id}/transactions', f'/api/users/{other.id}/events']:
                assert (await client.get(path)).json()['code'] == 403
            reply = (await client.get(f'/api/billing/mine?account_user_id={other.id}')).json()['data']
            assert reply['summary']['total_cost'] == '0.123456'
            assert [row['account_user_id'] for row in reply['items']] == [user.id]
            app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=user, is_super_admin=True)
            reply = (await client.get(f'/api/users/{other.id}/transactions')).json()
            assert reply['code'] == 0 and len(reply['data']['items']) == 1
            assert (await client.get('/api/users?order_by=password_hash')).json()['code'] == 422
    finally:
        app.dependency_overrides.clear()


async def test_order_filters_use_exact_owner_and_inclusive_dates():
    owner = await User.create(username='similar-name')
    other = await User.create(username='similar-name-2')
    today = date(2026, 11, 14)
    midnight = datetime(2026, 11, 13, 16, tzinfo=timezone.utc)
    for index, (user, created) in enumerate([
        (owner, midnight - timedelta(microseconds=1)),
        (owner, midnight),
        (other, midnight),
        (owner, midnight + timedelta(days=1)),
    ]):
        await RechargeOrder.create(account_user_id=user.id, user_id=user.id, amount=10,
            out_trade_no=f'order-{index}', status='paid', created_at=created)
    result = await account_controller.list_orders(owner.id, True, account_user_id=owner.id, start_date=today, end_date=today)
    assert result['pagination']['total'] == 1
    assert result['items'][0]['out_trade_no'] == 'order-1'
    assert result['items'][0]['account_user_id'] == owner.id
    with pytest.raises(Exception) as error:
        await account_controller.list_orders(owner.id, False, account_user_id=other.id)
    assert error.value.status_code == 403
    with pytest.raises(Exception) as error:
        await account_controller.list_orders(owner.id, True, end_date=date.max)
    assert error.value.status_code == 422
    result = await account_controller.list_orders(owner.id, True, end_date=today-timedelta(days=1))
    assert [item['out_trade_no'] for item in result['items']] == ['order-0']


async def test_audit_schema_upgrade_is_repeatable_and_keeps_records():
    from services.schema_compat import ensure_admin_events_schema
    event = await UserAdminEvent.create(account_user_id=1, operator_user_id=2, action='create')
    await ensure_admin_events_schema()
    await ensure_admin_events_schema()
    assert await UserAdminEvent.filter(id=event.id).exists()


async def test_account_totals_reconcile_actual_deductions_instead_of_estimates():
    from models.usage_record import ModelUsageRecord
    from auth.service import auth_service
    user = await User.create(username='reconcile')
    await UserWallet.create(user=user, balance=8)
    await ModelUsageRecord.create(novel_id=0, task_type=7, billing_type='text',
        model='estimated', account_user_id=user.id, user_id=user.id, cost=100)
    await BalanceTransaction.create(account_user_id=user.id, type='consume', change_amount=-2, balance_after=8)
    await BalanceTransaction.create(account_user_id=user.id, type='topup', change_amount=10, balance_after=10)
    assert (await user_controller.stats())['user_total_cost'] == 2
    assert (await user_controller.detail(user.id))['total_cost'] == 2
    assert (await user_controller.list_users(1, 20))['items'][0]['total_cost'] == 2
    assert (await auth_service.me(user)).total_cost == 2
