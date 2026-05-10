"""LLM client — wraps DeepSeek via the ``instructor`` library.

Uses the same pattern as ``scrap/llm.py``:
  instructor.from_openai(OpenAI(api_key=..., base_url="https://api.deepseek.com"))

Only used for decomposition.  Temperature is always forced to 0.
Set ``DEEPSEEK_API_KEY`` in the environment before calling any LLM method.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when an LLM call fails after all retries."""


def _make_client():
    """Build an instructor-wrapped DeepSeek client."""
    try:
        import instructor
        from openai import OpenAI
    except ImportError as exc:
        raise LLMError("Required packages missing. Run: pip install instructor openai") from exc

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise LLMError("DEEPSEEK_API_KEY environment variable is not set. Export it before running the pipeline.")

    return instructor.from_openai(
        OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
        )
    )


class LLMClient:
    """Thin wrapper around the configured LLM provider (DeepSeek via instructor)."""

    def __init__(
        self,
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        max_retries: int = 3,
        timeout_seconds: int = 120,
    ) -> None:
        self.provider = provider.lower()
        self.model = model
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            self._client = _make_client()
        return self._client

    # ------------------------------------------------------------------
    # Structured output via Pydantic model (instructor-style)
    # ------------------------------------------------------------------

    def call_model(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[T],
        max_retries: Optional[int] = None,
    ) -> T:
        """Call DeepSeek and return a validated Pydantic model instance.

        Args:
            system_prompt:   System instructions.
            user_prompt:     User request content.
            response_model:  Pydantic model class the response must conform to.
            max_retries:     Override instance default.

        Returns:
            Validated instance of *response_model*.

        Raises:
            LLMError: If all retries fail.
        """
        retries = max_retries if max_retries is not None else self.max_retries
        client = self._get_client()

        log.info(
            "[LLM] call_model model=%s response_model=%s",
            self.model,
            response_model.__name__,
        )

        last_exc: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                result = client.chat.completions.create(
                    model=self.model,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_model=response_model,
                    max_retries=2,
                )
                log.info("[LLM] call_model success on attempt %d", attempt)
                return result
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "[LLM] call_model attempt %d/%d failed: %s",
                    attempt,
                    retries,
                    exc,
                )

        raise LLMError(f"LLM call failed after {retries} attempts. Last error: {last_exc}") from last_exc

    # ------------------------------------------------------------------
    # Structured JSON output (dispatches to provider implementations)
    # ------------------------------------------------------------------

    def call_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Call the LLM and return a validated dict matching *json_schema*.

        Args:
            system_prompt: Instructions for the model.
            user_prompt:   The actual request payload.
            json_schema:   JSON Schema the model must conform to.

        Returns:
            Parsed dict matching the schema.

        Raises:
            LLMError: If the call fails after retries or the response
                      cannot be parsed.
        """
        if self.provider in ("openai", "azure_openai"):
            return self._call_openai(system_prompt, user_prompt, json_schema)
        if self.provider == "anthropic":
            return self._call_anthropic(system_prompt, user_prompt, json_schema)
        raise LLMError(f"Unsupported LLM provider: {self.provider}")

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _call_openai(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMError("openai package is not installed. Run: pip install openai") from exc

        client = OpenAI(timeout=self.timeout_seconds, max_retries=self.max_retries)

        response = client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": json_schema,
                },
            },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.choices[0].message.content
        if not content:
            raise LLMError("LLM returned an empty response.")

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM response is not valid JSON: {exc}\nResponse: {content[:500]}") from exc

    def _call_anthropic(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError("anthropic package is not installed. Run: pip install anthropic") from exc

        client = anthropic.Anthropic()

        schema_instruction = (
            f"\n\nRespond ONLY with valid JSON that strictly matches this JSON Schema:\n"
            f"{json.dumps(json_schema, indent=2)}"
        )

        message = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt + schema_instruction,
            messages=[{"role": "user", "content": user_prompt}],
        )

        content = message.content[0].text
        # Strip any markdown code fences
        content = content.strip()
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:])
        if content.endswith("```"):
            content = "\n".join(content.split("\n")[:-1])

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Anthropic response is not valid JSON: {exc}") from exc
