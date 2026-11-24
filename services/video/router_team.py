"""RouterTeam creative-center asynchronous video API (/v1/videos)."""

from services.platform.inline_media import decode_media
from services.video.base import VideoProviderError
from services.video.provider_http import structured_video_error
from services.video.public_media import public_media_url
from services.video.unified import UnifiedVideoGenerator
from utils.enums import TaskStatusEnum


class RouterTeamGenerator(UnifiedVideoGenerator):
    async def submit(self, prompt, *, duration, resolution, aspect_ratio, reference_images=None,
                     reference_file=None, **kwargs):
        body = {"model": self.config.model, "prompt": prompt, "duration_seconds": duration,
                "resolution": resolution}
        if aspect_ratio != "adaptive":
            body["aspect_ratio"] = aspect_ratio
        if reference_images:
            source, = reference_images
            if source.startswith("data:"):
                mime, data = decode_media(source, "image")
                reference_file = ("reference." + mime.split("/")[1], data, mime)
            else:
                body["input_reference"] = source
        if reference_file:
            _, data, mime = reference_file
            if mime not in {"image/png", "image/jpeg", "image/webp"} or len(data) > 8 * 1024**2:
                raise VideoProviderError("Router 首帧须为 8 MiB 以内的 PNG、JPEG 或 WebP")
        result = await self._request("POST", payload=body, file=reference_file)
        if result.get("error"):
            detail = structured_video_error(result, secrets=(self.config.api_key,))
            raise VideoProviderError(detail.get("message") or "Router 视频提交失败")
        task_id = result.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise VideoProviderError("Router 未返回任务编号", submission_uncertain=True)
        return task_id.strip()

    async def query(self, external_task_id, *, refresh=False):
        data = await self._request("GET", task_id=external_task_id)
        status = data.get("status")
        if status in {"submitted", "queued", "pending", "processing"}:
            state = TaskStatusEnum.running if status == "processing" else TaskStatusEnum.queued
            return self._build_result(state)
        if status == "failed":
            error = structured_video_error(data, secrets=(self.config.api_key,))
            return self._build_result(TaskStatusEnum.failed, error=error or {"message": "Router 视频生成失败"})
        if status != "completed":
            raise VideoProviderError("Router 返回了未知的视频任务状态")
        url = data.get("url") or data.get("output_url")
        if not url:
            url = next((item for item in data.get("result_urls") or []
                        if isinstance(item, str) and item), None)
        if not url:
            url = next((item["url"] for item in data.get("output") or []
                        if isinstance(item, dict) and item.get("type") == "video" and item.get("url")), None)
        if not url:
            raise VideoProviderError("Router 已完成任务但缺少成片地址")
        duration = data.get("duration_seconds") or data.get("seconds") or data.get("duration")
        if isinstance(duration, str):
            try:
                duration = float(duration)
            except ValueError:
                raise VideoProviderError("Router 返回的成片时长无效") from None
        return self._build_result(TaskStatusEnum.completed, progress=100, url=public_media_url(url),
                                  duration=duration, requires_output_duration=True)
