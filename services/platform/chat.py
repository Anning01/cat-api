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
_streams = {}
STREAM_FINALIZE_SECONDS = 30


def provider_client(config):
    return AsyncOpenAI(base_url=config.base_url, api_key=config.api_key, max_retries=0, timeout=CALL_TIMEOUT)


async def mark_failure(receipt, exc):
    rejected = isinstance(exc, APIStatusError) and 400 <= exc.status_code < 500 and exc.status_code != 408
    await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected" if rejected else "review")


RESULT_UNCONFIRMED = "平台未能确认完整模型结果，请凭请求编号查询状态"


class ChatStream(StreamingResponse):
    def __init__(self, client, stream, receipt, deadline, secret="", *, responses=False):
        self.responses = responses
        self.queue = asyncio.Queue(maxsize=32)
        self.detached = False
        self.deadline = deadline
        super().__init__(self.events(), media_type="text/event-stream",
            headers={**response_headers(stream, receipt.public_id, secret), "X-Accel-Buffering":"no"}, status_code=stream.status_code)
        task = asyncio.create_task(self.drain(client, stream, receipt, deadline, secret))
        _streams[task] = self
        task.add_done_callback(lambda done: _streams.pop(done, None))

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
            self.detach()

    def detach(self):
        self.detached = True
        # Wake both a blocked producer and a reader during forced cleanup.
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(None)

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
                            done = done or not self.responses
                            continue
                        try:
                            data = json.loads(value)
                            if self.responses:
                                result = data.get("response") or {}
                                provider_id = result.get("id") or provider_id
                                if data.get("type") in {"response.completed", "response.incomplete"}:
                                    # Only terminal usage confirms a billable response;
                                    # never reuse an earlier partial usage snapshot.
                                    usage = response_usage(result.get("usage"))
                                    done = True
                                failed = failed or data.get("type") in {"response.failed", "error"}
                                failed = failed or bool(result.get("error"))
                            else:
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


def response_usage(usage):
    if not isinstance(usage, dict):
        return None
    return {"prompt_tokens": usage.get("input_tokens"), "completion_tokens": usage.get("output_tokens"),
            "prompt_tokens_details": usage.get("input_tokens_details") or {}}


async def complete(ctx, body, key, *, responses=False):
    params = body.model_dump(mode="json", exclude_unset=True)
    from services.platform.temporary_media import resolve_payload
    outgoing = await resolve_payload(ctx.user.id, params)
    config, receipt = await admit(ctx, body.model, params, key, kind="text" if responses else ("text", "voice_design"))
    headers = {"X-Request-Id":str(receipt.public_id), "X-Cat-Request-Id":str(receipt.public_id), "Cache-Control":"no-store"}
    params = outgoing
    client = None
    deadline = asyncio.get_running_loop().time() + CALL_TIMEOUT
    try:
        client = provider_client(config)
        params["model"] = config.model
        params.setdefault("stream", False)
        limit_names = ("max_output_tokens",) if responses else ("max_tokens", "max_completion_tokens")
        if config.max_tokens and not any(params.get(name) for name in limit_names):
            params[limit_names[0]] = config.max_tokens
        from utils.model_reasoning import reasoning_parameters
        defaults = reasoning_parameters(config.thinking, config.reasoning_effort,
            text_api="responses" if responses else "chat_completions")
        for name, value in defaults.items():
            params.setdefault(name, value)
        extra = {name: params.pop(name) for name in (body.model_extra or {}) if name in params}
        if 'thinking' in params:
            extra['thinking'] = params.pop('thinking')
        if extra:
            params["extra_body"] = extra
        async with asyncio.timeout_at(deadline):
            endpoint = client.responses if responses else client.chat.completions
            raw_result = await endpoint.with_raw_response.create(**params)
            if not body.stream and raw_result.http_response.json().get("error"):
                await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected")
                raise UpstreamResponseError(raw_result.http_response, str(receipt.public_id), config.api_key)
        if body.stream:
            response = ChatStream(client, raw_result.http_response, receipt, deadline, config.api_key, responses=responses)
            client = None  # Stream owns its transport until usage is collected.
            return response
        raw = raw_result.http_response
        result = raw.json()
        if receipt.pricing.get("type") == "voice_design":
            from services.platform.voice_design import finish_voice
            await preserve_result(receipt, finish_voice(receipt, result))
        elif responses and result.get("status") not in {"completed", "incomplete"}:
            await mark_failure(receipt, ValueError("unconfirmed response status"))
        else:
            await preserve_result(receipt, finish(receipt, response_usage(result.get("usage")) if responses else result.get("usage"), result.get("id")))
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
        streams = dict(_streams)
        remaining = max(response.deadline - asyncio.get_running_loop().time() for response in streams.values())
        _, pending = await asyncio.wait(streams, timeout=max(0, remaining) + STREAM_FINALIZE_SECONDS)
        for task in pending:
            streams[task].detach()
            task.cancel()
        if pending:
            _, stuck = await asyncio.wait(pending, timeout=STREAM_FINALIZE_SECONDS)
            if stuck:
                logger.error("Chat shutdown cleanup exceeded budget: pending=%d", len(stuck))
                for task in stuck:
                    task.cancel()
