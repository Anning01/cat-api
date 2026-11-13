"""Personal balances, recharge orders and verified payment callbacks."""

from utils.messages import localized_message

import json
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from tortoise.expressions import Q
from tortoise.timezone import now as tz_now
from tortoise.transactions import in_transaction

from auth.models import RechargeOrder, User
from config import settings
from services import balance
from services.wechat_pay import WeChatPayError, wechat_pay_service

logger = logging.getLogger(__name__)



def _is_order_expired(order: RechargeOrder) -> bool:
    """待支付订单 15 分钟过期判定：
    1. 显式指定的 expires_at 已超时。
    2. 或从订单创建时间 created_at 算起已超过 15 分钟。
    """
    now = tz_now()
    if order.expires_at is not None:
        exp = order.expires_at
        if exp.tzinfo is None and now.tzinfo is not None:
            exp = exp.replace(tzinfo=now.tzinfo)
        elif exp.tzinfo is not None and now.tzinfo is None:
            exp = exp.replace(tzinfo=None)
        if now > exp:
            return True
    if order.created_at is not None:
        created = order.created_at
        if created.tzinfo is None and now.tzinfo is not None:
            created = created.replace(tzinfo=now.tzinfo)
        elif created.tzinfo is not None and now.tzinfo is None:
            created = created.replace(tzinfo=None)
        if now - created >= timedelta(minutes=15):
            return True
    return False


class AccountController:
    # ---- 余额 ----

    async def balance(self, user_id: int) -> dict:
        return {"account_user_id": user_id, "balance": await balance.get_balance(user_id)}

    async def top_up(
        self,
        user_id: int,
        amount: Decimal,
        operator_user_id: int | None,
        note: str,
    ) -> dict:
        result = await balance.top_up(user_id, amount, operator_user_id, note)
        return {"account_user_id": user_id, "balance": result}

    async def transactions(self, user_id: int, page: int, page_size: int) -> dict:
        return await balance.list_transactions(user_id, page, page_size)

    # ---- 充值订单（微信支付 Native 扫码） ----

    async def create_recharge(
        self,
        user_id: int,
        amount: Decimal,
        note: str = "",
    ) -> RechargeOrder:
        user = await User.get(id=user_id)
        if amount <= 0:
            raise HTTPException(400, localized_message("充值金额必须大于零"))

        now = tz_now()
        # 防刷单：限制单用户高频创建大量未支付订单
        recent_pending = await RechargeOrder.filter(
            user_id=user_id,
            status="pending",
            created_at__gte=now - timedelta(minutes=15),
        ).count()
        if recent_pending >= 10:
            raise HTTPException(429, localized_message("待支付订单过多，请稍候重试"))

        out_trade_no = f"REC{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        clean_user_name = "".join(ch for ch in user.nickname or user.username if ord(ch) <= 0xFFFF).strip()
        description = f"账户充值 - {clean_user_name}" if clean_user_name else "账户充值"
        attach = json.dumps({"user_id": user_id}, ensure_ascii=False)

        try:
            res = await wechat_pay_service.create_native_order(
                out_trade_no=out_trade_no,
                amount_yuan=amount,
                description=description,
                attach=attach,
            )
        except WeChatPayError as exc:
            raise HTTPException(400, str(exc)) from exc

        code_url = res.get("code_url")
        order = await RechargeOrder.create(
            out_trade_no=out_trade_no,
            account_user_id=user_id,
            user_id=user_id,
            amount=amount,
            status="pending",
            payment_method="wechat_native",
            code_url=code_url,
            expires_at=now + timedelta(minutes=15),
            note=note or "微信支付充值",
        )
        return order

    async def query_recharge(
        self,
        out_trade_no: str,
        user_id: int,
        is_super_admin: bool = False,
    ) -> tuple[RechargeOrder, Decimal]:
        order = await RechargeOrder.get_or_none(out_trade_no=out_trade_no)
        if order is None:
            raise HTTPException(404, localized_message("充值订单不存在"))

        if not is_super_admin and user_id != order.account_user_id:
            raise HTTPException(403, localized_message("无权查看该充值订单"))

        if order.status == "refunding":
            from services.recharge_refunds import recharge_refunds
            await recharge_refunds.sync(order)
        if order.status in {"pending", "expired"}:
            try:
                wx_res = await wechat_pay_service.query_order(out_trade_no)
                trade_state = wx_res.get("trade_state")
                if trade_state == "SUCCESS":
                    wechat_pay_service.validate_payment(wx_res, order.out_trade_no, order.amount)
                    await self._finish_recharge(order, wx_res.get("transaction_id"))
                    await order.refresh_from_db()
                elif trade_state in ("CLOSED", "REVOKED"):
                    await RechargeOrder.filter(id=order.id, status="pending").update(status="closed")
                    await order.refresh_from_db()
                elif trade_state == "PAYERROR":
                    await RechargeOrder.filter(id=order.id, status="pending").update(status="failed")
                    await order.refresh_from_db()
                elif _is_order_expired(order):
                    await RechargeOrder.filter(id=order.id, status="pending").update(status="expired")
                    await order.refresh_from_db()
            except Exception as exc:
                logger.warning("query_wechat_order_failed out_trade_no=%s: %s", out_trade_no, exc)
                if _is_order_expired(order):
                    await RechargeOrder.filter(id=order.id, status="pending").update(status="expired")
                    await order.refresh_from_db()

        current_balance = await balance.get_balance(order.account_user_id)
        return order, current_balance

    async def cleanup_recharge_orders(self) -> None:
        """异步轻量清理：
        1. 待支付订单 15 分钟过期：将 pending 且已过过期时间（或创建超过 15 分钟）的订单标记为 expired。
        2. 过期/关闭/失败超过 1 周（7 天）的订单彻底物理删除。
        由超管请求订单列表时通过 FastAPI BackgroundTasks 异步触发，无需定时任务或 Celery，执行极快。
        """
        try:
            now = tz_now()
            cutoff_15m = now - timedelta(minutes=15)
            # 批量将超期待支付订单置为 expired（创建超 15 分钟或已过 expires_at）
            await RechargeOrder.filter(
                Q(status="pending")
                & (
                    Q(expires_at__lt=now)
                    | Q(created_at__lt=cutoff_15m)
                )
            ).update(status="expired")

            # 彻底物理删除创建超过 7 天的失效订单
            cutoff_7d = now - timedelta(days=7)
            await RechargeOrder.filter(
                status__in=["expired", "closed", "failed"],
                created_at__lt=cutoff_7d,
            ).delete()
        except Exception as exc:
            logger.error("cleanup_recharge_orders failed: %s", exc, exc_info=True)

    async def list_orders(
        self,
        user_id: int,
        is_super_admin: bool,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """查询充值订单：超管可看全平台，普通用户仅看本人创建的充值订单。"""
        query = RechargeOrder.all()
        if not is_super_admin:
            query = query.filter(account_user_id=user_id)

        if status:
            query = query.filter(status=status)

        if search:
            search_str = search.strip()
            matched_user_ids = await User.filter(
                Q(username__icontains=search_str) | Q(nickname__icontains=search_str)
            ).values_list("id", flat=True)

            search_filter = (
                Q(out_trade_no__icontains=search_str)
                | Q(transaction_id__icontains=search_str)
                | Q(note__icontains=search_str)
            )
            if matched_user_ids:
                search_filter = search_filter | Q(user_id__in=matched_user_ids)

            query = query.filter(search_filter)

        total = await query.count()
        offset = (page - 1) * page_size
        orders = (
            await query
            .order_by("-id")
            .offset(offset)
            .limit(page_size)
        )

        user_ids = {order.user_id for order in orders}
        user_map: dict[int, User] = {}
        if user_ids:
            users = await User.filter(id__in=list(user_ids))
            user_map = {u.id: u for u in users}

        items = []
        for order in orders:
            curr_status = order.status
            if curr_status == "pending" and _is_order_expired(order):
                curr_status = "expired"
                await RechargeOrder.filter(id=order.id, status="pending").update(
                    status="expired", updated_at=tz_now()
                )

            user = user_map.get(order.user_id)
            items.append({
                "id": order.id,
                "out_trade_no": order.out_trade_no,
                "account_user_id": order.account_user_id,
                "user_id": order.user_id,
                "username": user.username if user else "",
                "nickname": user.nickname if user else "",
                "amount": order.amount,
                "status": curr_status,
                "payment_method": order.payment_method,
                "code_url": order.code_url,
                "transaction_id": order.transaction_id,
                "paid_at": order.paid_at,
                "expires_at": order.expires_at,
                "note": order.note,
                "refund_id": order.refund_id,
                "refunded_at": order.refunded_at,
                "refund_reason": order.refund_reason,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
            })

        pages = (total + page_size - 1) // page_size if total else 0
        return {
            "items": items,
            "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": pages,
        }

    async def refund_recharge(
        self,
        out_trade_no: str,
        operator_user_id: int | None = None,
        reason: str = "",
    ) -> RechargeOrder:
        from services.recharge_refunds import recharge_refunds
        return await recharge_refunds.request(out_trade_no, operator_user_id, reason)

    async def _finish_recharge(
        self,
        order: RechargeOrder,
        transaction_id: str | None = None,
    ) -> bool:
        async with in_transaction():
            locked = await RechargeOrder.filter(id=order.id).select_for_update().first()
            if locked is None or locked.status not in {"pending", "expired", "closed", "failed"}:
                return False

            locked.status = "paid"
            locked.transaction_id = transaction_id or f"TXN_{locked.out_trade_no}"
            locked.paid_at = tz_now()
            await locked.save()

            await balance.top_up(
                user_id=locked.account_user_id,
                amount=locked.amount,
                operator_user_id=locked.user_id,
                note=f"微信支付充值 (单号: {locked.out_trade_no})",
            )
            return True

    async def mock_pay_recharge(
        self,
        out_trade_no: str,
        user_id: int,
        is_super_admin: bool = False,
    ) -> tuple[RechargeOrder, Decimal]:
        if not settings.WECHAT_PAY_MOCK or settings.AUTH_PROVIDER == "qiling":
            raise HTTPException(404, localized_message("充值订单不存在"))

        order = await RechargeOrder.get_or_none(out_trade_no=out_trade_no)
        if order is None:
            raise HTTPException(404, localized_message("充值订单不存在"))

        if not is_super_admin and user_id != order.account_user_id:
            raise HTTPException(403, localized_message("无权操作该充值订单"))

        await self._finish_recharge(order, f"MOCK_TXN_{uuid.uuid4().hex[:10]}")
        await order.refresh_from_db()
        current_balance = await balance.get_balance(order.account_user_id)
        return order, current_balance

    async def handle_wechat_notify(
        self, body_bytes: bytes, headers: Any = None
    ) -> dict[str, Any]:

        ts = headers.get("wechatpay-timestamp") or headers.get("Wechatpay-Timestamp") or "" if headers else ""
        nonce = headers.get("wechatpay-nonce") or headers.get("Wechatpay-Nonce") or "" if headers else ""
        sig = headers.get("wechatpay-signature") or headers.get("Wechatpay-Signature") or "" if headers else ""
        serial = headers.get("wechatpay-serial") or headers.get("Wechatpay-Serial") or "" if headers else ""

        if not (ts and nonce and sig and serial):
            logger.error("wechat_notify_missing_signature_headers")
            return {"code": "FAIL", "message": "缺少微信签名请求头"}

        if ts and nonce and sig:
            body_str = body_bytes.decode("utf-8", errors="replace")
            if not wechat_pay_service.verify_signature(ts, nonce, body_str, sig, serial):
                logger.error("wechat_notify_signature_verification_failed")
                return {"code": "FAIL", "message": "签名验证失败"}

        try:
            data = json.loads(body_bytes.decode("utf-8"))
        except Exception as exc:
            logger.error("wechat_notify_invalid_json: %s", exc)
            return {"code": "FAIL", "message": "JSON 解析失败"}

        if not isinstance(data, dict):
            return {"code": "FAIL", "message": "无效通知"}
        resource = data.get("resource")
        if not isinstance(resource, dict):
            return {"code": "FAIL", "message": "缺少 resource"}

        try:
            decrypted = wechat_pay_service.decrypt_callback(
                ciphertext=resource.get("ciphertext", ""),
                nonce=resource.get("nonce", ""),
                associated_data=resource.get("associated_data", ""),
            )
        except Exception as exc:
            logger.error("wechat_notify_decrypt_failed: %s", exc)
            return {"code": "FAIL", "message": "密文解密失败"}

        if not isinstance(decrypted, dict):
            return {"code": "FAIL", "message": "无效通知"}
        out_trade_no = decrypted.get("out_trade_no")
        trade_state = decrypted.get("trade_state")
        transaction_id = decrypted.get("transaction_id")
        if out_trade_no and trade_state == "SUCCESS":
            order = await RechargeOrder.get_or_none(out_trade_no=out_trade_no)
            if order:
                try:
                    wechat_pay_service.validate_payment(decrypted, order.out_trade_no, order.amount)
                except WeChatPayError:
                    return {"code": "FAIL", "message": "支付金额不匹配或订单身份不匹配"}
                await self._finish_recharge(order, transaction_id)
                logger.info("wechat_notify_order_paid out_trade_no=%s txn=%s", out_trade_no, transaction_id)

        return {"code": "SUCCESS", "message": "成功"}



account_controller = AccountController()
