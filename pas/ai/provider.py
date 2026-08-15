"""Model provider abstraction (spec 39).

The rest of the platform depends on :class:`LLMProvider`, never on a vendor
SDK, so adding Anthropic/Bedrock/local models later is a new subclass rather
than a cross-cutting change.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import AppConfig
from .schema import response_format_for

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """A call to the model provider failed."""


class SchemaViolation(ProviderError):
    """The provider returned data that did not satisfy the contract."""


@dataclass
class Usage:
    """What one model call actually cost (spec 38)."""

    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    cached: bool = False


@dataclass
class Completion:
    """A structured result plus the metadata needed to audit it."""

    data: Any
    raw: str
    usage: Usage
    extra: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Interface every model backend implements."""

    name: str = "abstract"

    @abstractmethod
    def complete_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 8000,
        temperature: float | None = None,
    ) -> Completion:
        """Return an instance of ``schema`` validated from the model response."""

    @abstractmethod
    def complete_text(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4000,
        temperature: float | None = None,
    ) -> Completion:
        """Return free-form text. Used only for narrative surfaces."""


class OpenRouterProvider(LLMProvider):
    """OpenAI-compatible provider backed by OpenRouter.

    OpenRouter reports real spend per call in ``usage.cost``, so cost tracking
    here is measured rather than estimated from a price table that would drift.
    """

    name = "openrouter"

    def __init__(self, config: AppConfig, max_retries: int = 2) -> None:
        from openai import OpenAI  # imported lazily to keep import cost off the UI path

        from ..config import OPENROUTER_BASE_URL

        self._config = config
        self._max_retries = max_retries
        self._client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=config.require_api_key(),
        )

    # -- internals ---------------------------------------------------------

    def _usage_from(self, response: Any, model: str, latency_ms: int, attempts: int) -> Usage:
        raw_usage = getattr(response, "usage", None)
        return Usage(
            provider=self.name,
            model=model,
            prompt_tokens=getattr(raw_usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(raw_usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(raw_usage, "total_tokens", 0) or 0,
            cost_usd=float(getattr(raw_usage, "cost", 0.0) or 0.0),
            latency_ms=latency_ms,
            attempts=attempts,
        )

    def _call(self, **kwargs: Any) -> tuple[Any, int]:
        started = time.monotonic()
        response = self._client.chat.completions.create(**kwargs)
        return response, int((time.monotonic() - started) * 1000)

    # -- public API --------------------------------------------------------

    def complete_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 8000,
        temperature: float | None = None,
    ) -> Completion:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 2):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "response_format": response_format_for(schema),
                    "max_tokens": max_tokens,
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature

                response, latency = self._call(**kwargs)
                raw = response.choices[0].message.content or ""
                if not raw.strip():
                    raise SchemaViolation("Provider returned an empty response body.")

                data = schema.model_validate_json(raw)
                return Completion(
                    data=data,
                    raw=raw,
                    usage=self._usage_from(response, model, latency, attempt),
                )

            except (ValidationError, json.JSONDecodeError, SchemaViolation) as exc:
                # Contract violation: feed the error back so the retry can correct
                # itself rather than reproducing the same malformed shape.
                last_error = exc
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response did not satisfy the required "
                            f"schema. Error:\n{exc}\n"
                            "Return corrected data matching the schema exactly."
                        ),
                    },
                ]
            except Exception as exc:  # transport / provider errors
                last_error = exc
                if attempt > self._max_retries:
                    break
                time.sleep(min(2 ** attempt, 8))

        raise ProviderError(
            f"{model} failed after {self._max_retries + 1} attempts: {last_error}"
        ) from last_error

    def complete_text(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 4000,
        temperature: float | None = None,
    ) -> Completion:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature
                response, latency = self._call(**kwargs)
                raw = response.choices[0].message.content or ""
                return Completion(
                    data=raw,
                    raw=raw,
                    usage=self._usage_from(response, model, latency, attempt),
                )
            except Exception as exc:
                last_error = exc
                if attempt > self._max_retries:
                    break
                time.sleep(min(2 ** attempt, 8))
        raise ProviderError(f"{model} failed: {last_error}") from last_error
