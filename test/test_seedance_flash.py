import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from services.billing.catalog import VIDEO_PRICING
from services.platform.model_aliases import alias_base
from services.platform.videos import VideoRequest, video_options
from services.video.capabilities import capabilities_for, validate_selection
from services.video.factory import video_generator_factory
from services.video.seedance import SeedanceGenerator

MODEL = "seedance_2_5_flash"


def config():
    return SimpleNamespace(
        name="Flash", model="doubao-seedance-2-5-flash-261115",
        video_model_type=MODEL, image_model_type=None, task_type=4, task_types=[4],
        api_protocol="volcengine_ark", base_url="https://vendor.example/api/v3",
        api_key="fixture", pricing=VIDEO_PRICING[MODEL],
    )


def test_flash_capabilities_and_selection():
    caps = capabilities_for(MODEL)
    assert caps.resolutions == ("480p", "720p")
    assert (caps.max_reference_images, caps.max_reference_videos, caps.max_reference_audios) == (10, 5, 5)
    assert capabilities_for("seedance_2_5").max_reference_images == 30
    assert capabilities_for(MODEL, "novelvids").max_reference_images == 10
    assert alias_base(config()) == "seedance-2.5-flash"
    options = dict(generation_mode="reference", resolution="720p", aspect_ratio="16:9",
                   duration=30, output_format="mov", generate_audio=True)
    assert validate_selection(MODEL, **options).duration == 30
    assert validate_selection(MODEL, **{**options, "duration": -1}).duration == -1
    for override in ({"resolution": "1080p"}, {"duration": 31}, {"generation_mode": "keyframes"}):
        with pytest.raises(HTTPException):
            validate_selection(MODEL, **{**options, **override})


@pytest.mark.parametrize("kind,limit", [("image", 10), ("video", 5), ("audio", 5)])
def test_flash_reference_limits(kind, limit):
    def request(count):
        return VideoRequest(model="seedance-2.5-flash", prompt="Pan", duration=30,
            references=[{"type": kind, "url": f"https://media.example/{i}"} for i in range(count)])
    assert video_options(config(), request(limit).model_dump(mode="json")) == VIDEO_PRICING[MODEL]
    with pytest.raises(HTTPException) as error:
        video_options(config(), request(limit + 1).model_dump(mode="json"))
    assert error.value.status_code == 422


async def test_flash_uses_ark_payload(monkeypatch):
    seen = []
    async def dispatch(request):
        seen.append(json.loads(request.content))
        assert request.url.path == "/api/v3/contents/generations/tasks"
        return httpx.Response(200, json={"id": "flash-task"})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(dispatch), **kwargs))
    generator = video_generator_factory.create(config())
    assert isinstance(generator, SeedanceGenerator)
    assert await generator.submit("Pan", duration=30, output_format="mov",
        reference_audios=["https://media.example/audio.wav"]) == "flash-task"
    assert seen[0]["model"] == config().model
    assert seen[0]["duration"] == 30 and seen[0]["output_format"] == "mov"
    assert seen[0]["content"][-1]["role"] == "reference_audio"
