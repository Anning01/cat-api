"""OpenAI-compatible text transport. Content stays in memory; durable receipts contain costs only."""
import asyncio
import json
import codecs
import logging

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from openai import APIError, APIStatusError, AsyncOpenAI
from auth.models import PlatformCallReceipt
from services.platform.calls import CALL_TIMEOUT, admit, finish, recover_measured, preserve_result
from services.platform.http_contract import UpstreamResponseError, error_body, redact_secret, response_headers

logger = logging.getLogger(__name__)
_streams = set()


def provider_client(config):
    return AsyncOpenAI(base_url=config.base_url, api_key=config.api_key, max_retries=0, timeout=CALL_TIMEOUT)


async def mark_failure(receipt, exc):
    rejected = isinstance(exc, APIStatusError) and 400 <= exc.status_code < 500 and exc.status_code != 408
    await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected" if rejected else "review")


RESULT_UNCONFIRMED = "平台未能确认完整模型结果，请凭请求编号查询状态"


class ChatStream(StreamingResponse):
    def __init__(self, client, stream, receipt, deadline, secret=""):
        self.queue = asyncio.Queue(maxsize=32)
        self.detached = False
        super().__init__(self.events(), media_type="text/event-stream",
            headers={**response_headers(stream, receipt.public_id, secret), "X-Accel-Buffering":"no"}, status_code=stream.status_code)
        task = asyncio.create_task(self.drain(client, stream, receipt, deadline, secret))
        _streams.add(task)
        task.add_done_callback(_streams.discard)

    async def put(self, item):
        if not self.detached:
            await self.queue.put(item)

    async def events(self):
        while (event := await self.queue.get()) is not None:
            yield event

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.detached = True
            # Wake the single producer if a disconnected client left its queue full.
            while not self.queue.empty():
                self.queue.get_nowait()

    async def drain(self, client, stream, receipt, deadline, secret):
        usage = None
        provider_id = None
        decoder = codecs.getincrementaldecoder("utf-8")()
        pending = ""
        done = False
        failed = False
        try:
            async with asyncio.timeout_at(deadline):
                async for chunk in stream.aiter_bytes():
                    # Forward original SSE bytes, including event names, comments and extensions.
                    await self.put(chunk)
                    pending += decoder.decode(chunk)
                    lines = pending.split("\n")
                    pending = lines.pop()
                    for line in lines:
                        if not line.startswith("data:"):
                            continue
                        value = line[5:].strip()
                        if value == "[DONE]":
                            done = True
                            continue
                        try:
                            data = json.loads(value)
                            provider_id = data.get("id") or provider_id
                            usage = data.get("usage") or usage
                            failed = failed or bool(data.get("error"))
                        except (ValueError, AttributeError):
                            pass
                    if len(pending) > 1024 * 1024:
                        pending = ""
            if failed:
                await mark_failure(receipt, ValueError("provider stream error"))
            elif done:
                await preserve_result(receipt, finish(receipt, usage, provider_id))
            else:
                await mark_failure(receipt, ValueError("incomplete stream"))
        except asyncio.CancelledError as exc:
            await mark_failure(receipt, exc)
            raise
        except Exception as exc:
            await mark_failure(receipt, exc)
            payload = error_body(502, RESULT_UNCONFIRMED)
            if isinstance(exc, APIError) and isinstance(exc.body, dict):
                payload = exc.body if "error" in exc.body else {"error": exc.body}
            logger.warning("Developer chat stream failed request_id=%s type=%s", receipt.public_id, type(exc).__name__)
            content = redact_secret(json.dumps(payload, ensure_ascii=False).encode(), secret)
            await self.put(b"data: " + content + b"\n\n")
        finally:
            try:
                await client.close()
            finally:
                await self.put(None)


async def complete(ctx, body, key):
    params = body.model_dump(mode="json", exclude_unset=True)
    config, receipt = await admit(ctx, body.model, params, key)
    headers = {"X-Request-Id":str(receipt.public_id), "Cache-Control":"no-store"}
    client = None
    deadline = asyncio.get_running_loop().time() + CALL_TIMEOUT
    try:
        client = provider_client(config)
        params["model"] = config.model
        params.setdefault("stream", False)
        if config.max_tokens and not (body.max_tokens or body.max_completion_tokens):
            params["max_tokens"] = config.max_tokens
        extra = {name: params.pop(name) for name in (body.model_extra or {}) if name in params}
        if body.thinking is not None:
            extra["thinking"] = params.pop("thinking")
        if extra:
            params["extra_body"] = extra
        async with asyncio.timeout_at(deadline):
            raw_result = await client.chat.completions.with_raw_response.create(**params)
            if not body.stream and raw_result.http_response.json().get("error"):
                await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected")
                raise UpstreamResponseError(raw_result.http_response, str(receipt.public_id), config.api_key)
        if body.stream:
            response = ChatStream(client, raw_result.http_response, receipt, deadline, config.api_key)
            client = None  # Stream owns its transport until usage is collected.
            return response
        raw = raw_result.http_response
        result = raw.json()
        await preserve_result(receipt, finish(receipt, result.get("usage"), result.get("id")))
        from fastapi import Response
        return Response(raw.content, status_code=raw.status_code, headers=response_headers(raw, receipt.public_id, config.api_key))
    except asyncio.CancelledError as exc:
        await mark_failure(receipt, exc)
        raise
    except Exception as exc:
        await mark_failure(receipt, exc)
        if isinstance(exc, UpstreamResponseError):
            raise
        if isinstance(exc, APIStatusError):
            raise UpstreamResponseError(exc.response, str(receipt.public_id), config.api_key) from None
        logger.warning("Developer chat request failed request_id=%s type=%s", receipt.public_id, type(exc).__name__)
        raise HTTPException(502, RESULT_UNCONFIRMED, headers=headers) from None
    finally:
        if client is not None:
            await client.close()


async def settle_periodically():
    while True:
        await asyncio.sleep(60)
        try:
            await recover_measured()
        except Exception:
            logger.error("Platform settlement retry deferred")


async def stop_streams():
    if _streams:
        _, pending = await asyncio.wait(list(_streams), timeout=15)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
