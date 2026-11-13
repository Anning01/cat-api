"""Billing visibility follows individual users."""
from auth.deps import AuthContext


def billing_scope(ctx: AuthContext) -> int | None:
    return None if ctx.is_super_admin else ctx.user.id
