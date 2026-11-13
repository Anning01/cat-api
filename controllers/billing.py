"""账单计费控制器。"""

from auth.deps import AuthContext


def billing_scope(ctx: AuthContext) -> tuple[int | None, int | None]:
    """返回 (team_id, user_id) 过滤条件：超管看全部，创作者只看自己。"""
    if ctx.is_super_admin:
        return None, None
    if ctx.membership and ctx.membership.role == "creator":
        return ctx.team_id, ctx.user.id
    return ctx.team_id, None
