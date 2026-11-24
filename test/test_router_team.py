import httpx
import pytest
from fastapi import HTTPException
from types import SimpleNamespace

from services.video.capabilities import capabilities_for, validate_selection
from services.video.factory import video_generator_factory
from services.video.base import VideoProviderError
from utils.enums import TaskStatusEnum


def adapter(kind="muse_video", model="muse-video"):
    return video_generator_factory.create(SimpleNamespace(
        api_protocol="router_team", video_model_type=kind, model=model,
        base_url="https://router.example/v1", api_key="fixture"))


@pytest.mark.parametrize("kind,model,seconds,resolution,ratio", [
    ("muse_video", "muse-video", 5, "720p", "9:16"),
    ("grok_imagine_video_1_5", "grok-imagine-video-1.5", 1, "480p", "adaptive"),
])
async def test_documented_wire_contract(monkeypatch, kind, model, seconds, resolution, ratio):
    import json
    gen = adapter(kind, model)
    states = iter(["submitted", "processing", "completed"])
    def dispatch(request):
        assert request.headers["authorization"] == "Bearer fixture"
        if request.method == "POST":
            assert request.url.path == "/v1/videos"
            assert json.loads(request.content) == {
                "model": model, "duration_seconds": seconds, "prompt": "Pan", "resolution": resolution,
                "input_reference": "https://cdn.example/frame.png",
                **({"aspect_ratio": ratio} if ratio != "adaptive" else {}),
            }
            return httpx.Response(200, json={"task_id": "job1", "status": "submitted"})
        assert request.url.path == "/v1/videos/job1"
        return httpx.Response(200, json={"status": next(states), "duration_seconds": str(seconds),
                                        "result_urls": ["https://cdn.example/video.mp4"]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(dispatch), **kw))
    task = await gen.submit("Pan", duration=seconds, aspect_ratio=ratio, resolution=resolution,
                            reference_images=["https://cdn.example/frame.png"])
    assert (await gen.query(task))["status"] == TaskStatusEnum.queued
    assert (await gen.query(task))["status"] == TaskStatusEnum.running
    result = await gen.query(task)
    assert result["url"].endswith("/video.mp4") and result["metadata"]["duration"] == seconds


async def test_muse_discrete_seconds_and_reference_upload(monkeypatch):
    caps = capabilities_for("muse_video", "router_team")
    assert caps.duration_choices == (5, 6, 8, 10)
    with pytest.raises(HTTPException):
        validate_selection("muse_video", generation_mode="reference", resolution="720p", aspect_ratio="16:9",
                           duration=7, output_format="mp4", generate_audio=False)
    gen = adapter()
    original = httpx.AsyncClient
    def dispatch(request):
        assert request.headers["content-type"].startswith("multipart/form-data")
        assert b'name="input_reference"' in request.content and b'PNG' in request.content
        return httpx.Response(200, json={"status": "submitted"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(dispatch), **kw))
    with pytest.raises(VideoProviderError) as exc:
        await gen.submit("pan", duration=5, resolution="720p", aspect_ratio="16:9",
                         reference_file=("frame.png", b"PNG", "image/png"))
    assert exc.value.submission_uncertain


async def test_final_output_and_failures(monkeypatch):
    gen = adapter()
    data = iter([{"status": "completed", "output": [{"type": "image", "url": "cover"},
                 {"type": "video", "url": "https://cdn.example/final.mp4"}]},
                 {"status": "failed", "error_message": "fixture upstream error"},
                 {"status": "completed", "thumbnail": "https://cdn.example/cover.png"}])
    async def response(*args, **kwargs):
        return next(data)
    monkeypatch.setattr(gen, "_request", response)
    assert (await gen.query("job"))["url"].endswith("final.mp4")
    failure = await gen.query("job")
    assert failure["status"] == TaskStatusEnum.failed
    assert "fixture" not in failure["metadata"]["error"]["message"]
    with pytest.raises(VideoProviderError):
        await gen.query("job")


async def test_catalog_exposes_workbench_capabilities_without_private_fields():
    from models.config import AiModelConfig
    from services.platform.catalog import model_catalog

    await AiModelConfig.create(
        name="Router Grok", model="grok-imagine-video-1.5", video_model_type="grok_imagine_video_1_5",
        api_protocol="router_team", base_url="https://private.example/v1", api_key="test-only",
        task_type=4, is_active=True, pricing={"type":"video","billing_unit":"second","prices":{"480p":1,"720p":0}},
    )
    entry, = await model_catalog()
    caps = entry["video_capabilities"]
    assert caps["resolutions"] == ["480p"] and caps["default_resolution"] == "480p"
    assert caps["aspect_ratios"] == ["adaptive"] and caps["duration_max"] == 15
    assert caps["max_reference_images"] == 1 and caps["max_reference_videos"] == 0
    assert caps["output_formats"] == ["mp4"] and not caps["supports_auto_duration"]
    assert not {"api_protocol", "api_key", "base_url"}.intersection(caps)


async def test_router_missing_duration_never_charges_requested_seconds(monkeypatch):
    from services.platform.videos import measured

    gen = adapter()
    async def query(*args, **kwargs):
        return {"status": "completed", "url": "https://cdn.example/result.mp4"}
    monkeypatch.setattr(gen, "_request", query)
    result = await gen.query("finished")
    assert result["url"] and result["status"] == TaskStatusEnum.completed
    inputs = {"duration": 5, "has_video_reference": False}
    assert measured(inputs, result["metadata"], {"billing_unit": "second"}) is None
