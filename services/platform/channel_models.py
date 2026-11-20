"""Administrator-only discovery and idempotent import of compatible channel models."""
import hashlib
import json

import httpx
from fastapi import HTTPException
from tortoise.transactions import in_transaction

from controllers.config import ai_model_config_controller
from models.config import AiModelConfig


def channel_root(base_url):
    try:
        url = httpx.URL(base_url.strip().rstrip("/"))
    except httpx.InvalidURL:
        raise HTTPException(422, "上游地址无效") from None
    if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment:
        raise HTTPException(422, "请输入不含凭据和查询参数的上游地址")
    root = str(url).removesuffix("/videos").rstrip("/")
    return root if root.endswith("/v1") else root + "/v1"


async def discover_models(base_url, key):
    root = channel_root(base_url)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            async with client.stream("GET", root + "/models", headers={"Authorization": "Bearer " + key}) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 2 * 1024**2:
                        raise ValueError()
                    content.extend(chunk)
        rows = json.loads(content)["data"]
        if not isinstance(rows, list):
            raise ValueError()
        return list(dict.fromkeys(row["id"] for row in rows if isinstance(row, dict)
                                  and isinstance(row.get("id"), str) and 0 < len(row["id"].strip()) <= 200))
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(502, "上游模型目录不可用，可手动填写模型 ID") from None


async def import_models(template, model_ids):
    root = channel_root(template.base_url)
    ids = list(dict.fromkeys(m.strip() for m in model_ids))
    if not all(ids) or any(len(m) > 200 for m in ids):
        raise HTTPException(422, "模型 ID 须为 1–200 个字符")
    if template.api_protocol not in {"openai_video", "openai_compatible", "openrouter_compatible"}:
        raise HTTPException(422, "该通道使用原生配置入口")
    result = []
    async with in_transaction() as db:
        if db.capabilities.dialect == "postgres":
            lock = int.from_bytes(hashlib.sha256(root.encode()).digest()[:8], "big", signed=True)
            await db.execute_query("SELECT pg_advisory_xact_lock($1)", [lock])
        for model in ids:
            existing = await AiModelConfig.filter(scope="official", api_protocol=template.api_protocol,
                        base_url=root, api_key=template.api_key, model=model).first()
            if existing:
                if (existing.task_types or [existing.task_type]) != (template.task_types or [template.task_type]):
                    raise HTTPException(409, "已有模型使用不同操作，请在原配置中核对")
                result.append(existing.id)
                continue
            config = template.model_copy(update={"name":model[:100], "base_url":root, "model":model})
            created = await ai_model_config_controller.create(config, scope="official")
            result.append(created.id)
    return result
