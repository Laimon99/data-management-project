from __future__ import annotations

import json
import time
from typing import Protocol

import httpx

from .config import LlmERSettings
from .models import Decision, LlmDecision, MatchGroup, RiskFlag
from .prompt import build_messages, candidate_sort_key
from .schema import response_text_format


class LlmClient(Protocol):
    model: str

    def decide(self, group: MatchGroup) -> LlmDecision:
        ...


class MockLlmClient:
    """Deterministic offline client used by tests and smoke runs."""

    def __init__(self, model: str = "mock-llm") -> None:
        self.model = model

    def decide(self, group: MatchGroup) -> LlmDecision:
        if not group.candidates:
            return LlmDecision(
                decision=Decision.NON_MATCH,
                matched_candidate_id=None,
                confidence=0.95,
                reason="No candidate was provided.",
                risk_flags=[RiskFlag.INSUFFICIENT_EVIDENCE],
            )

        ranked = sorted(group.candidates, key=candidate_sort_key)
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        distance = best.distance_m if best.distance_m is not None else 1_000_000.0
        name_sim = float(best.components.get("name_sim") or 0.0)
        street_sim = float(best.components.get("street_sim") or 0.0)
        phone_match = float(best.components.get("phone_match") or 0.0) == 1.0
        website_match = float(best.components.get("website_match") or 0.0) == 1.0

        if (
            second is not None
            and float(second.components.get("name_sim") or 0.0) >= 0.75
            and (second.distance_m or 1_000_000.0) <= 100
            and name_sim >= 0.75
        ):
            return LlmDecision(
                decision=Decision.UNCERTAIN,
                matched_candidate_id=None,
                confidence=0.62,
                reason="Multiple nearby candidates look plausible.",
                risk_flags=[RiskFlag.MULTIPLE_PLAUSIBLE_CANDIDATES],
            )

        if (phone_match or website_match) and distance <= 1000:
            return LlmDecision(
                decision=Decision.MATCH,
                matched_candidate_id=best.candidate_id,
                confidence=0.92,
                reason="Contact evidence supports the best candidate.",
                risk_flags=[],
            )

        if distance <= 50 and (name_sim >= 0.75 or street_sim >= 0.80):
            return LlmDecision(
                decision=Decision.MATCH,
                matched_candidate_id=best.candidate_id,
                confidence=0.90,
                reason="The best candidate is nearby with strong name or street similarity.",
                risk_flags=[],
            )

        if distance > 300:
            return LlmDecision(
                decision=Decision.NON_MATCH,
                matched_candidate_id=None,
                confidence=0.82,
                reason="The nearest candidate is too far away without contact evidence.",
                risk_flags=[RiskFlag.LARGE_DISTANCE],
            )

        return LlmDecision(
            decision=Decision.UNCERTAIN,
            matched_candidate_id=None,
            confidence=0.60,
            reason="Evidence is insufficient for a safe decision.",
            risk_flags=[RiskFlag.INSUFFICIENT_EVIDENCE],
        )


class OpenAIResponsesClient:
    """OpenAI Responses API client using Structured Outputs."""

    def __init__(self, settings: LlmERSettings) -> None:
        if not settings.openai_api_key:
            raise ValueError("DATAMAN_OPENAI_API_KEY is required for --mode openai.")
        self.model = settings.llm_match_model
        self._settings = settings

    def decide(self, group: MatchGroup) -> LlmDecision:
        payload = {
            "model": self.model,
            "input": build_messages(group),
            "text": response_text_format(),
        }
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self._settings.openai_max_retries + 1):
            try:
                with httpx.Client(timeout=self._settings.openai_timeout_seconds) as client:
                    response = client.post(
                        f"{self._settings.openai_base_url.rstrip('/')}/responses",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                return parse_response_payload(response.json())
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not _retryable_status(exc.response.status_code) or (
                    attempt >= self._settings.openai_max_retries
                ):
                    raise
                time.sleep(_retry_delay_seconds(self._settings, attempt, exc.response))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self._settings.openai_max_retries:
                    raise
                time.sleep(_retry_delay_seconds(self._settings, attempt, None))
        raise RuntimeError("OpenAI request failed after retries.") from last_error


def _retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code in {500, 502, 503, 504}


def _retry_delay_seconds(
    settings: LlmERSettings,
    attempt: int,
    response: httpx.Response | None,
) -> float:
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after is not None:
        try:
            return min(float(retry_after), settings.openai_retry_max_seconds)
        except ValueError:
            pass
    return min(
        settings.openai_retry_initial_seconds * (2**attempt),
        settings.openai_retry_max_seconds,
    )


def parse_response_payload(payload: dict) -> LlmDecision:
    text = extract_output_text(payload)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI response did not contain valid JSON: {text!r}") from exc
    return LlmDecision.model_validate(raw)


def extract_output_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if isinstance(content, dict):
                if isinstance(content.get("text"), str):
                    return content["text"]
                if isinstance(content.get("output_text"), str):
                    return content["output_text"]
    raise ValueError("OpenAI response did not include output text.")
