"""Guangying's asynchronous video API with public URL references."""
from urllib.parse import quote

import httpx

from services.platform.http_contract import check_upstream_response
from services.video.base import BaseVideoGenerator, VideoProviderError
from services.video.provider_http import structured_video_error
from utils.enums import TaskStatusEnum


class GuangyingGenerator(BaseVideoGenerator):
    async def _request(self, method, path, *, key=None, payload=None):
        submitting = method == "POST"
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        if key:
            headers["Idempotency-Key"] = str(key)
        root = self.config.base_url.rstrip("/").removesuffix("/v1")
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.request(method, f"{root}/v1/{path}", headers=headers, json=payload)
        except httpx.HTTPError as exc:
            not_sent = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
            raise VideoProviderError("光影接口连接失败", submission_uncertain=submitting and not not_sent) from None
        check_upstream_response(response)
        try:
            envelope = response.json()
        except ValueError:
            envelope = None
        if not response.is_success or not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
            error = structured_video_error(envelope, secrets=(self.config.api_key,))
            uncertain = submitting and (response.is_success or response.status_code == 408 or response.status_code >= 500)
            raise VideoProviderError(error.get("message") or "光影接口响应无效", submission_uncertain=uncertain)
        return envelope["data"]

    async def submit(self, prompt, negative_prompt="", subjects=None, duration=5, aspect_ratio="9:16", **kwargs):
        from services.platform.images import media_url

        key = kwargs.get("platform_request_key")
        if not key:
            raise VideoProviderError("光影生成请求缺少幂等键")
        assets = []
        counts = {"image": 0, "video": 0, "audio": 0}
        for kind, source in kwargs["ordered_references"]:
            counts[kind] += 1
            assets.append({"type": kind, "name": f"{kind}{counts[kind]}", "url": media_url(source)})
        data = await self._request("POST", "video/generations", key=key, payload={
            "model": self.config.model, "prompt": prompt, "duration": int(duration),
            "ratio": aspect_ratio, "resolution": kwargs["resolution"], "nativeFace": False, "assets": assets,
        })
        task = data.get("id")
        if not isinstance(task, str) or not task.strip():
            raise VideoProviderError("光影未返回任务编号", submission_uncertain=True)
        return task.strip()

    async def query(self, external_task_id):
        data = await self._request("GET", "tasks/" + quote(external_task_id, safe=""))
        status = data.get("status")
        if status == "succeeded":
            url = data.get("downloadUrl") or next((r.get("url") for r in data.get("results") or []
                if isinstance(r, dict) and r.get("type") == "video" and r.get("url")), None)
            if not url:
                raise VideoProviderError("光影已完成任务但缺少成片地址")
            return self._build_result(TaskStatusEnum.completed, progress=100, url=url)
        if status == "failed":
            error = structured_video_error(data, secrets=(self.config.api_key,))
            return self._build_result(TaskStatusEnum.failed, error=error or {"message": "光影视频生成失败"})
        if status in {"queued", "processing", "requires_attention"}:
            state = TaskStatusEnum.queued if status == "queued" else TaskStatusEnum.running
            return self._build_result(state, progress=data.get("progress"), provider_status=status)
        raise VideoProviderError("光影返回未知任务状态")
