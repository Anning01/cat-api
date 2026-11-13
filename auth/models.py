"""鉴权与账户相关数据模型（仅在 AUTH_ENABLED=true 时注册到 Tortoise）。"""

from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import UserStatusEnum


class User(AbstractBaseModel):
    """用户表。微信扫码登录（二期）接入后 unionid/openid 由对应 Provider 填充。"""

    username = fields.CharField(
        max_length=100, unique=True, description="登录用户名（唯一）"
    )
    password_hash = fields.CharField(
        max_length=255, default="!", description="旧数据库兼容字段"
    )
    nickname = fields.CharField(max_length=100, default="", description="昵称")
    avatar_url = fields.CharField(
        max_length=500, default="", description="头像地址"
    )
    unionid = fields.CharField(max_length=64, null=True, description="微信 unionid")
    openid = fields.CharField(max_length=64, null=True, description="微信 openid")
    is_super_admin = fields.BooleanField(
        default=False, db_index=True, description="是否平台超级管理员"
    )
    status = fields.IntField(
        default=UserStatusEnum.active.value,
        description="账号状态：0 停用 / 1 正常",
    )

    class Meta:
        table = "users"
        table_description = "用户表"

    def __str__(self):
        return f"{self.username}({self.nickname or '-'})"


class UserSession(AbstractBaseModel):
    """登录会话表。库存 token 哈希，可吊销、可过期。"""

    token_hash = fields.CharField(
        max_length=64, unique=True, description="会话令牌哈希"
    )
    user = fields.ForeignKeyField(
        "models.User", related_name="sessions", on_delete=fields.CASCADE,
        description="会话所属用户",
    )
    expires_at = fields.DatetimeField(description="过期时间")
    last_seen_at = fields.DatetimeField(null=True, description="最近活跃时间")

    class Meta:
        table = "user_sessions"
        table_description = "登录会话表"

    def __str__(self):
        return f"session:{self.user_id}"


class QilingIdentity(AbstractBaseModel):
    issuer = fields.CharField(max_length=255)
    subject = fields.CharField(max_length=100)
    user = fields.OneToOneField("models.User", related_name="qiling_identity", on_delete=fields.CASCADE)

    class Meta:
        table = "qiling_identities"
        unique_together = (("issuer", "subject"),)


class QilingLoginAttempt(AbstractBaseModel):
    token_hash = fields.CharField(max_length=64, unique=True)
    upstream_state = fields.CharField(max_length=200)
    issuer = fields.CharField(max_length=255)
    binding_user = fields.ForeignKeyField("models.User", null=True, on_delete=fields.CASCADE)
    expires_at = fields.DatetimeField(db_index=True)

    class Meta:
        table = "qiling_login_attempts"


class BalanceTransaction(AbstractBaseModel):
    """账户余额流水表：充值/消费/调整，不可变。balance_after 冗余用于对账。"""

    account_user_id = fields.IntField(db_index=True)
    change_amount = fields.DecimalField(
        max_digits=18, decimal_places=6, description="变动金额（正=入账，负=出账）"
    )
    balance_after = fields.DecimalField(
        max_digits=18, decimal_places=6, description="变动后余额"
    )
    type = fields.CharField(
        max_length=16, description="流水类型：topup/consume/adjust"
    )
    usage_record_id = fields.IntField(null=True, description="关联计费流水 ID")
    operator_user_id = fields.IntField(
        null=True, description="操作人 User.id（充值/调整）"
    )
    note = fields.CharField(max_length=255, default="", description="备注")

    class Meta:
        table = "account_balance_transactions"
        table_description = "账户余额流水表"

    def __str__(self):
        return f"{self.type}:{self.change_amount}->{self.balance_after}"


class RechargeOrder(AbstractBaseModel):
    """账户充值订单表：记录微信支付 Native 扫码充值单及支付状态。"""

    out_trade_no = fields.CharField(
        max_length=64, unique=True, db_index=True, description="商户订单号"
    )
    account_user_id = fields.IntField(db_index=True)
    user_id = fields.IntField(db_index=True, description="创建订单用户 ID")
    amount = fields.DecimalField(
        max_digits=18, decimal_places=2, description="充值金额（元）"
    )
    status = fields.CharField(
        max_length=20, default="pending", db_index=True, description="状态：pending/paid/expired/closed/failed/refunding/refunded/refund_closed"
    )
    payment_method = fields.CharField(
        max_length=32, default="wechat_native", description="支付方式"
    )
    code_url = fields.CharField(
        max_length=512, null=True, description="微信 Native 支付二维码 URL"
    )
    transaction_id = fields.CharField(
        max_length=128, null=True, db_index=True, description="微信支付流水号"
    )
    paid_at = fields.DatetimeField(null=True, description="支付成功时间")
    expires_at = fields.DatetimeField(null=True, description="订单过期时间")
    note = fields.CharField(max_length=255, default="", description="充值备注")
    refund_id = fields.CharField(max_length=128, null=True, db_index=True, description="微信退款单号")
    refunded_at = fields.DatetimeField(null=True, description="退款成功时间")
    refund_reason = fields.CharField(max_length=255, default="", description="退款原因")

    class Meta:
        table = "account_recharge_orders"
        table_description = "账户充值订单表"

    def __str__(self):
        return f"Order({self.out_trade_no}, {self.amount}, {self.status})"


class PlatformApiKey(AbstractBaseModel):
    user = fields.ForeignKeyField("models.User", on_delete=fields.CASCADE)
    name = fields.CharField(max_length=80)
    token_hash = fields.CharField(max_length=64, unique=True)
    preview = fields.CharField(max_length=20)
    revoked_at = fields.DatetimeField(null=True)


    class Meta:
        table = "account_api_keys"


class PlatformCallReceipt(AbstractBaseModel):
    legacy_scope_id = fields.IntField(null=True)
    public_id = fields.UUIDField(unique=True)
    dedup_key = fields.CharField(max_length=64, unique=True)
    payload_hash = fields.CharField(max_length=64)
    account_user_id = fields.IntField(db_index=True)
    user_id = fields.IntField()
    api_key_id = fields.IntField(null=True)
    model_config_id = fields.IntField(db_index=True)
    model_name = fields.CharField(max_length=100)
    model = fields.CharField(max_length=200)
    pricing = fields.JSONField()
    state = fields.CharField(max_length=16, db_index=True, default="submitted")
    provider_id = fields.CharField(max_length=255, null=True)
    usage = fields.JSONField(null=True)
    usage_record_id = fields.IntField(null=True)


    class Meta:
        table = "account_call_receipts"


class StudioKeyGrant(AbstractBaseModel):
    key = fields.OneToOneField("models.PlatformApiKey", on_delete=fields.CASCADE)


    class Meta:
        table = "account_studio_grants"


class StudioMediaLease(AbstractBaseModel):
    object_key = fields.CharField(max_length=220, unique=True)
    bucket = fields.CharField(max_length=64)
    region = fields.CharField(max_length=64)
    account_user_id = fields.IntField(db_index=True)
    byte_length = fields.BigIntField()
    expires_epoch = fields.BigIntField(db_index=True)
    retry_epoch = fields.BigIntField(null=True)


    class Meta:
        table = "account_media_leases"


class PlatformVideoJob(AbstractBaseModel):
    receipt = fields.OneToOneField("models.PlatformCallReceipt", on_delete=fields.CASCADE)
    route_hash = fields.CharField(max_length=64)
    inputs = fields.JSONField()
    status = fields.CharField(max_length=20, default="queued", db_index=True)
    progress = fields.IntField(default=0)
    output = fields.JSONField(null=True)
    poll_after = fields.BigIntField(default=0, db_index=True)
    poll_token = fields.UUIDField(null=True)


    class Meta:
        table = "account_video_jobs"


class UserWallet(AbstractBaseModel):
    user = fields.OneToOneField("models.User", on_delete=fields.RESTRICT)
    balance = fields.DecimalField(max_digits=18, decimal_places=6, default=0)


class UserAdminEvent(AbstractBaseModel):
    account_user_id = fields.IntField(db_index=True)
    operator_user_id = fields.IntField()
    action = fields.CharField(max_length=32)
    note = fields.CharField(max_length=255, default="")

    class Meta:
        table = "account_admin_events"


class AccountMigration(AbstractBaseModel):
    name = fields.CharField(max_length=100, unique=True)
