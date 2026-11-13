"""Proposed media-job wire types. No paid execution routes are enabled yet."""
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.video_enhancement.contract import EnhancementResolution


class MediaJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(pattern=r"^nv-[1-9][0-9]{0,9}$")
    media_id: int = Field(gt=0)
    request_id: UUID


class TranscriptionRequest(MediaJobRequest):
    pass


class EnhancementRequest(MediaJobRequest):
    output_resolution: EnhancementResolution


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: Decimal = Field(ge=0, description="Seconds, inclusive")
    end: Decimal = Field(ge=0, description="Seconds, exclusive")
    text: str

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class MediaJobResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: UUID
    object: Literal["transcription", "video_enhancement"]
    model: str
    status: Literal["queued", "in_progress", "completed", "failed", "review"]
    billing_status: Literal["submitted", "processing", "measured", "settling", "completed", "rejected", "review"]
    duration_seconds: Decimal | None = Field(None, gt=0)
    text: str | None = None
    segments: list[TranscriptSegment] | None = None
    download_url: str | None = None
