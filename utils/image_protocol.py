from enum import StrEnum


class ImageApiProtocol(StrEnum):
    """Supported image-generation wire protocols."""

    openai_compatible = "openai_compatible"
    openrouter_compatible = "openrouter_compatible"
    volcengine_ark = "volcengine_ark"
    novelvids = "novelvids"
    openai_video = "openai_video"
    guangying_fixed = "guangying_fixed"
    unified_video = "unified_video"
    minimax = "minimax"
    autodl = "autodl"
    dashscope = "dashscope"
    volcengine_mediakit = "volcengine_mediakit"
    volcengine_openspeech = "volcengine_openspeech"
