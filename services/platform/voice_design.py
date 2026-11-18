"""MiMo voice design: unchanged WAV results, measured output duration and account settlement."""
import base64
import binascii
from decimal import Decimal, ROUND_HALF_UP
import io
from math import isfinite
import wave

from fastapi import HTTPException

from auth.models import PlatformCallReceipt
from services.platform.calls import record_measurement

MODEL = "mimo-v2.5-tts-voicedesign"


def voice_pricing(rates):
    if not isinstance(rates, dict) or rates.get("type") != "voice_design" or rates.get("billing_unit") != "second" or rates.get("currency", "CNY") != "CNY":
        raise ValueError("音色设计须配置 CNY 按秒价格")
    for name in ("price_per_second", "discount"):
        value = rates.get(name, 1 if name == "discount" else None)
        if type(value) not in {int, float} or not isfinite(value) or value < 0 or (name == "discount" and value == 0):
            raise ValueError("音色设计价格或折扣无效")
    return rates


def voice_options(config, body):
    try:
        rates = voice_pricing(config.pricing)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if (config.task_types or [config.task_type]) != [12] or config.model != MODEL or config.api_protocol != "openai_compatible" or config.text_api != "chat_completions":
        raise HTTPException(422, "请选择 MiMo 音色设计 Chat Completions 渠道")
    messages = body.get("messages") or []
    if [message.get("role") for message in messages] != ["user", "assistant"] or any(
        not isinstance(message.get("content"), str) or not message["content"].strip() for message in messages
    ):
        raise HTTPException(422, "须依次提供 user 音色描述和 assistant 试听台词")
    audio = body.get("audio")
    if not isinstance(audio, dict) or audio.get("format") != "wav" or set(audio) - {"format", "optimize_text_preview"}:
        raise HTTPException(422, "音色设计仅支持 WAV 输出参数")
    if "optimize_text_preview" in audio and type(audio["optimize_text_preview"]) is not bool:
        raise HTTPException(422, "optimize_text_preview 须为布尔值")
    if body.get("stream") or body.get("n", 1) != 1 or body.get("tools") or body.get("modalities", ["audio"]) != ["audio"]:
        raise HTTPException(422, "音色设计仅支持非流式单音频输出")
    return rates


def wav_usage(result):
    choices = result.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("Missing audio choice")
    audio = (choices[0].get("message") or {}).get("audio") or {}
    encoded = audio.get("data")
    if not isinstance(encoded, str):
        raise ValueError("Missing WAV data")
    try:
        data = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            frame_size = wav.getnchannels() * wav.getsampwidth()
            if frames <= 0 or rate <= 0 or frame_size <= 0 or len(wav.readframes(frames + 1)) != frames * frame_size:
                raise ValueError("Incomplete WAV")
    except (binascii.Error, wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV") from exc
    # Keep exact sample counts for billing; seconds is the public usage contract.
    return {"seconds":float(Decimal(frames) / rate), "frames":frames, "sample_rate":rate}


def voice_cost(usage, rates):
    voice_pricing(rates)
    frames, rate = usage["frames"], usage["sample_rate"]
    if type(frames) is not int or type(rate) is not int or frames <= 0 or rate <= 0:
        raise ValueError("Missing measured WAV duration")
    return (Decimal(frames) / rate * Decimal(str(rates["price_per_second"])) *
            Decimal(str(rates.get("discount", 1)))).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def finish_voice(receipt, result):
    try:
        usage = wav_usage(result)
    except (ValueError, TypeError, AttributeError):
        # Preserve provider bytes for client validation, but never guess billable duration.
        await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="review", provider_id=result.get("id"))
        return
    await record_measurement(receipt, usage, result.get("id"))
