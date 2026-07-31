"""Local translation presets and conservative token-cost estimates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


PRICING_UPDATED = "2026-07-11"
MODEL_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-5.6-luna": (1.00, 6.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-sol": (5.00, 30.00),
}
QUALITY_PRESETS: dict[str, tuple[str, str]] = {
    "economy": ("gpt-5.6-luna", "none"),
    "balanced": ("gpt-5.6-terra", "low"),
    "best": ("gpt-5.6-sol", "high"),
}

_REASONING_OUTPUT_FACTORS = {
    "none": (1.00, 1.10),
    "low": (1.05, 1.35),
    "medium": (1.15, 1.70),
    "high": (1.30, 2.30),
    "xhigh": (1.55, 3.10),
    "max": (1.90, 4.20),
}


@dataclass(frozen=True)
class CostEstimate:
    """Estimated standard-priority translation cost in US dollars."""

    model: str
    input_tokens: int
    output_tokens_low: int
    output_tokens_high: int
    cost_low: float
    cost_high: float


def preset_for(model: str, reasoning_effort: str) -> str:
    """Return the matching named preset or ``custom``."""
    pair = (model.strip(), reasoning_effort.strip())
    for name, values in QUALITY_PRESETS.items():
        if pair == values:
            return name
    return "custom"


def estimate_for_duration(
    duration_seconds: float,
    model: str,
    reasoning_effort: str,
) -> CostEstimate | None:
    """Estimate subtitle token volume from media runtime."""
    minutes = max(1.0, duration_seconds / 60.0)
    input_tokens = int(math.ceil(minutes * 250))
    visible_output_tokens = int(math.ceil(minutes * 225))
    return _estimate(
        input_tokens,
        visible_output_tokens,
        model,
        reasoning_effort,
    )


def estimate_for_srt(
    path: str | Path,
    model: str,
    reasoning_effort: str,
) -> CostEstimate | None:
    """Estimate cost from the actual SRT character count."""
    text = Path(path).read_text(encoding="utf-8-sig")
    input_tokens = max(1, _rough_tokens(text))
    visible_output_tokens = max(1, int(math.ceil(input_tokens * 0.95)))
    return _estimate(
        input_tokens,
        visible_output_tokens,
        model,
        reasoning_effort,
    )


def cost_from_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Calculate standard-priority cost from API-reported token usage."""
    rates = MODEL_PRICING_PER_MILLION.get(model)
    if not rates:
        return None
    input_rate, output_rate = rates
    return (
        max(0, input_tokens) * input_rate
        + max(0, output_tokens) * output_rate
    ) / 1_000_000


def _estimate(
    input_tokens: int,
    visible_output_tokens: int,
    model: str,
    reasoning_effort: str,
) -> CostEstimate | None:
    rates = MODEL_PRICING_PER_MILLION.get(model)
    if not rates:
        return None
    low_factor, high_factor = _REASONING_OUTPUT_FACTORS.get(
        reasoning_effort,
        (1.20, 2.50),
    )
    output_low = int(math.ceil(visible_output_tokens * low_factor))
    output_high = int(math.ceil(visible_output_tokens * high_factor))
    input_rate, output_rate = rates
    input_cost = input_tokens * input_rate / 1_000_000
    return CostEstimate(
        model,
        input_tokens,
        output_low,
        output_high,
        input_cost + output_low * output_rate / 1_000_000,
        input_cost + output_high * output_rate / 1_000_000,
    )


def _rough_tokens(text: str) -> int:
    ascii_count = sum(1 for character in text if ord(character) < 128)
    non_ascii_count = len(text) - ascii_count
    return int(math.ceil(ascii_count / 4 + non_ascii_count / 2))
