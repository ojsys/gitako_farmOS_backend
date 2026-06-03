"""Co-pilot orchestration — ties the provider to the farm-scoped tools."""
from __future__ import annotations

from .anomalies import detect_anomalies
from .prompts import CHAT_SYSTEM
from .providers import get_llm_provider
from .tools import farm_tool_specs, make_executor


def answer_question(*, farm, user, message: str, history: list[dict] | None = None) -> dict:
    provider = get_llm_provider()
    executor = make_executor(farm, user)
    return provider.chat(
        system=CHAT_SYSTEM,
        user_message=message,
        history=history or [],
        tool_specs=farm_tool_specs(),
        tool_executor=executor,
    )


def diagnose_image(*, image_b64: str, media_type: str, prompt: str = "") -> dict:
    return get_llm_provider().diagnose(image_b64=image_b64, media_type=media_type, prompt=prompt)


def farm_anomalies(*, farm) -> list[dict]:
    return detect_anomalies(farm)
