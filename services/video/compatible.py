"""The wire capabilities explicitly configured for a compatible video model."""
from typing import Annotated, Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator


class CompatibleVideoOptions(BaseModel):
    sizes: list[Annotated[str, Field(pattern=r"^[1-9][0-9]{1,3}x[1-9][0-9]{1,3}$")]] = Field(
        default_factory=lambda: ["720x1280","1280x720","1792x1024","1024x1792"], min_length=1,max_length=48)
    seconds: list[Annotated[int, Field(strict=True, gt=0, le=3600)]] = Field(default_factory=lambda:[4,8,12],min_length=1,max_length=100)
    reference_inputs: list[Literal["url","file"]] = Field(default_factory=lambda:["url","file"])

    @field_validator("sizes", "seconds", "reference_inputs")
    @classmethod
    def unique(cls, values):
        return list(dict.fromkeys(values))

    @property
    def resolutions(self):
        return list(dict.fromkeys(f"{min(map(int,size.split('x')))}p" for size in self.sizes))


def compatible_options(options):
    try:
        return CompatibleVideoOptions.model_validate((options or {}).get("video", {}))
    except ValidationError:
        raise HTTPException(422, "请检查通道支持的像素尺寸、时长与参考图输入方式") from None
