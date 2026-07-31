"""Translate SRT subtitles with configurable OpenAI models and language prompts."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import app_paths
import chunker
import languages
import network_tls
from operation_control import CancellationToken


_API_BASE_URL = "https://api.openai.com/v1"
_REQUEST_TIMEOUT_SECONDS = 240
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 5
_MAX_OUTPUT_TOKENS = 8192
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_ERROR_RESPONSE_BYTES = 64 * 1024
_DEFAULT_MODEL = os.environ.get("OPENAI_TRANSLATION_MODEL", "gpt-5.6-luna")
_DEFAULT_REASONING_EFFORT = os.environ.get("OPENAI_TRANSLATION_REASONING", "low")
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_SRT_TIMING_LINE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*"
    r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}[^\n]*)\s*$"
)


class TranslationFormatError(RuntimeError):
    """Raised when a model response changes SRT structure or timestamps."""


class OpenAIRequestError(RuntimeError):
    """Raised when the OpenAI HTTPS API rejects or cannot complete a request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after = retry_after


def test_api_key(api_key: str, model: str = _DEFAULT_MODEL) -> None:
    """Validate OpenAI access without submitting subtitle content."""
    if not api_key.strip():
        raise ValueError("An OpenAI API key is required.")
    _request_json(
        "GET",
        f"/models/{quote(model, safe='')}",
        api_key.strip(),
        timeout=30,
    )


def translate_srt(
    srt_path: str,
    api_key: str,
    model: str = _DEFAULT_MODEL,
    reasoning_effort: str = _DEFAULT_REASONING_EFFORT,
    *,
    source_language: str = "en",
    target_language: str = "vi",
    prompt_template: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    cancellation_token: CancellationToken | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Translate one text subtitle while preserving its exact SRT structure."""
    path = Path(srt_path)
    if not path.is_file():
        raise FileNotFoundError(f"SRT file not found: '{srt_path}'")
    if path.stat().st_size > _MAX_SOURCE_BYTES:
        raise ValueError(
            "Subtitle file is too large to translate safely "
            f"(limit: {_MAX_SOURCE_BYTES // (1024 * 1024)} MB)."
        )
    if not api_key.strip():
        raise ValueError("An OpenAI API key is required.")

    source = languages.get_language(source_language)
    target = languages.get_language(target_language)
    if source.code == target.code:
        raise ValueError("Source and target languages must be different.")

    prompt = languages.render_translation_prompt(
        source.code,
        target.code,
        template_override=prompt_template,
    )
    chunks = chunker.chunk_srt(str(path))
    print(f"Prepared {len(chunks)} translation chunk(s).")
    print(
        f"Translating {source.name} to {target.name} with model '{model}' "
        f"and reasoning '{reasoning_effort or 'model default'}'."
    )

    translated_chunks: list[str] = []
    for index, source_chunk in enumerate(chunks, start=1):
        if cancellation_token:
            cancellation_token.raise_if_cancelled()
        if progress_callback:
            progress_callback(index, len(chunks))
        translated_chunks.append(
            _translate_chunk(
                api_key.strip(),
                source_chunk,
                prompt,
                model,
                reasoning_effort,
                index,
                len(chunks),
                cancellation_token,
                event_callback,
            )
        )

    if cancellation_token:
        cancellation_token.raise_if_cancelled()
    result = chunker.reassemble_srt(translated_chunks)
    _validate_srt_structure(
        path.read_text(encoding="utf-8-sig"),
        result,
        require_indices=False,
    )
    print("Translation complete.")
    return result


def save_translated_srt(
    content: str,
    original_video_path: str,
    *,
    target_language: str = "vi",
    output_directory: str | Path | None = None,
) -> str:
    """Save a final translated SRT beside its media or in a chosen directory."""
    video = Path(original_video_path).expanduser().resolve()
    target = languages.get_language(target_language)
    destination = Path(output_directory).expanduser() if output_directory else video.parent
    output_path = app_paths.unique_output_path(
        video,
        destination,
        suffix=f" [{target.name}]",
        extension=".srt",
    )
    output_path.write_text(content, encoding="utf-8")
    print(f"Saved translated subtitle to: {output_path}")
    return str(output_path)


def _translate_chunk(
    api_key: str,
    source_chunk: str,
    prompt: str,
    model: str,
    reasoning_effort: str,
    chunk_number: int,
    total_chunks: int,
    cancellation_token: CancellationToken | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """Translate and structurally validate one chunk with bounded retries."""
    print(f"Translating chunk {chunk_number} of {total_chunks}...")
    last_error: Exception | None = None
    instructions = prompt
    for attempt in range(1, _MAX_RETRIES + 1):
        if cancellation_token:
            cancellation_token.raise_if_cancelled()
        try:
            request: dict[str, object] = {
                "model": model,
                "instructions": instructions,
                "input": source_chunk,
                "max_output_tokens": _MAX_OUTPUT_TOKENS,
            }
            if reasoning_effort:
                request["reasoning"] = {"effort": reasoning_effort}
            request["store"] = False
            if cancellation_token is None:
                response = _request_json(
                    "POST",
                    "/responses",
                    api_key,
                    body=request,
                )
            else:
                response = _request_json(
                    "POST",
                    "/responses",
                    api_key,
                    body=request,
                    cancellation_token=cancellation_token,
                )
            translated = _strip_markdown_fence(_extract_output_text(response))
            _validate_srt_structure(source_chunk, translated)
            if event_callback:
                usage = response.get("usage")
                event_callback(
                    "chunk_completed",
                    {
                        "chunk": chunk_number,
                        "total_chunks": total_chunks,
                        "attempt": attempt,
                        "model": model,
                        "reasoning_effort": reasoning_effort,
                        "usage": usage if isinstance(usage, dict) else {},
                    },
                )
            return translated
        except TranslationFormatError as exc:
            last_error = exc
            if event_callback:
                event_callback(
                    "retry",
                    {
                        "chunk": chunk_number,
                        "attempt": attempt,
                        "reason": "format validation",
                    },
                )
            instructions = (
                f"{prompt}\n\nThe previous response changed SRT structure. "
                "On this retry, copy every cue number and timestamp byte-for-byte "
                "from the input and return only the corrected SRT."
            )
            if attempt < _MAX_RETRIES:
                print(
                    f"Translation attempt {attempt}/{_MAX_RETRIES} failed: {exc}. "
                    f"Retrying in {_RETRY_DELAY_SECONDS}s."
                )
                if cancellation_token:
                    cancellation_token.wait(_RETRY_DELAY_SECONDS)
                else:
                    time.sleep(_RETRY_DELAY_SECONDS)
        except OpenAIRequestError as exc:
            last_error = exc
            if not exc.retryable:
                raise
            if attempt < _MAX_RETRIES:
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else _RETRY_DELAY_SECONDS
                )
                delay = max(0.0, min(delay, 30.0))
                print(
                    f"Translation attempt {attempt}/{_MAX_RETRIES} failed: {exc}. "
                    f"Retrying in {delay:g}s."
                )
                if event_callback:
                    event_callback(
                        "retry",
                        {
                            "chunk": chunk_number,
                            "attempt": attempt,
                            "reason": "temporary API error",
                            "status_code": exc.status_code,
                            "delay_seconds": delay,
                        },
                    )
                if cancellation_token:
                    cancellation_token.wait(delay)
                else:
                    time.sleep(delay)

    raise RuntimeError(
        f"Failed to translate chunk {chunk_number} after {_MAX_RETRIES} attempts."
    ) from last_error


def _request_json(
    method: str,
    path: str,
    api_key: str,
    *,
    body: dict[str, object] | None = None,
    timeout: int = _REQUEST_TIMEOUT_SECONDS,
    cancellation_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """Send one authenticated JSON request without persisting credentials."""
    if cancellation_token:
        cancellation_token.raise_if_cancelled()
    payload = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else None
    )
    request = Request(  # noqa: S310
        f"{_API_BASE_URL}{path}",
        data=payload,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SubtitleTranslator/0.9",
        },
    )
    try:
        # _API_BASE_URL is a fixed OpenAI HTTPS endpoint.
        with urlopen(  # noqa: S310  # nosec B310
            request,
            timeout=timeout,
            context=network_tls.verified_ssl_context(),
        ) as response:
            raw = _read_limited_response(response, _MAX_RESPONSE_BYTES)
    except HTTPError as exc:
        raw_error = exc.read(_MAX_ERROR_RESPONSE_BYTES)
        message = _api_error_message(raw_error) or str(exc.reason)
        message = message.replace(api_key, "[redacted]")
        retry_after = _retry_after_seconds(
            exc.headers.get("Retry-After") if exc.headers else None
        )
        raise OpenAIRequestError(
            f"OpenAI request failed ({exc.code}): {message}",
            status_code=exc.code,
            retryable=exc.code in _RETRYABLE_STATUS_CODES,
            retry_after=retry_after,
        ) from exc
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise OpenAIRequestError(
            f"Could not reach OpenAI: {reason}",
            retryable=True,
        ) from exc

    if cancellation_token:
        cancellation_token.raise_if_cancelled()
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIRequestError(
            "OpenAI returned an invalid JSON response.",
            retryable=True,
        ) from exc
    if not isinstance(decoded, dict):
        raise OpenAIRequestError("OpenAI returned an unexpected response.")
    return decoded


def _read_limited_response(response: Any, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise OpenAIRequestError(
            "OpenAI returned a response larger than the application safety limit."
        )
    return data


def _extract_output_text(response: dict[str, Any]) -> str:
    """Collect text parts from a completed Responses API payload."""
    if response.get("status") not in {None, "completed"}:
        error = response.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "The response did not complete.")
        else:
            details = response.get("incomplete_details")
            reason = details.get("reason") if isinstance(details, dict) else ""
            message = (
                f"The response did not complete ({reason})."
                if reason
                else "The response did not complete."
            )
        raise OpenAIRequestError(message, retryable=True)

    texts: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
    if not texts:
        raise OpenAIRequestError("OpenAI returned no translated subtitle text.")
    return "\n".join(texts)


def _api_error_message(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    message = error.get("message")
    return message if isinstance(message, str) else ""


def _validate_srt_structure(
    source: str,
    translated: str,
    *,
    require_indices: bool = True,
) -> None:
    """Require identical cue count, ordering, and timestamp lines."""
    source_cues = _parse_srt_cues(source, "Source")
    translated_cues = _parse_srt_cues(translated, "Translated")
    if not source_cues:
        raise TranslationFormatError("Source chunk does not contain valid SRT cues.")
    if len(source_cues) != len(translated_cues):
        raise TranslationFormatError(
            f"Cue count changed from {len(source_cues)} to {len(translated_cues)}."
        )
    for position, (source_cue, translated_cue) in enumerate(
        zip(source_cues, translated_cues),
        start=1,
    ):
        source_index, source_timing, source_has_text = source_cue
        translated_index, translated_timing, translated_has_text = translated_cue
        if require_indices and source_index != translated_index:
            raise TranslationFormatError(f"Cue number changed at position {position}.")
        if _normalize_timing(source_timing) != _normalize_timing(translated_timing):
            raise TranslationFormatError(f"Timestamp changed at cue {source_index}.")
        if source_has_text and not translated_has_text:
            raise TranslationFormatError(
                f"Dialogue text is missing at cue {source_index}."
            )


def _parse_srt_cues(
    value: str,
    label: str,
) -> list[tuple[str, str, bool]]:
    """Parse every block and reject preambles or malformed model output."""
    blocks = chunker._parse_srt_blocks(value.replace("\r\n", "\n"))
    cues: list[tuple[str, str, bool]] = []
    for position, block in enumerate(blocks, start=1):
        if len(block) < 2 or not re.fullmatch(r"\s*\d+\s*", block[0]):
            raise TranslationFormatError(
                f"{label} SRT block {position} has no valid cue number."
            )
        timing_match = _SRT_TIMING_LINE_RE.fullmatch(block[1])
        if not timing_match:
            raise TranslationFormatError(
                f"{label} SRT block {position} has no valid timestamp."
            )
        cues.append(
            (
                block[0].strip(),
                timing_match.group(1),
                any(line.strip() for line in block[2:]),
            )
        )
    return cues


def _normalize_timing(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace(".", ",")


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, min(float(value), 30.0))
    except ValueError:
        return None


def _strip_markdown_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1])
    return stripped.strip() + "\n"
