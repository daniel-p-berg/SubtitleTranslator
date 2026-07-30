"""Translate SRT subtitles with configurable OpenAI models and language prompts."""

from __future__ import annotations

import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import app_paths
import chunker
import languages


_API_BASE_URL = "https://api.openai.com/v1"
_REQUEST_TIMEOUT_SECONDS = 240
_MAX_RETRIES = 3
_RETRY_DELAY_SECONDS = 5
_MAX_OUTPUT_TOKENS = 8192
_DEFAULT_MODEL = os.environ.get("OPENAI_TRANSLATION_MODEL", "gpt-5.6-luna")
_DEFAULT_REASONING_EFFORT = os.environ.get("OPENAI_TRANSLATION_REASONING", "low")
_SRT_BLOCK_RE = re.compile(
    r"(?ms)^\s*(\d+)\s*\n"
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*"
    r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}[^\n]*)\n"
)


class TranslationFormatError(RuntimeError):
    """Raised when a model response changes SRT structure or timestamps."""


class OpenAIRequestError(RuntimeError):
    """Raised when the OpenAI HTTPS API rejects or cannot complete a request."""


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
) -> str:
    """Translate one text subtitle while preserving its exact SRT structure."""
    path = Path(srt_path)
    if not path.is_file():
        raise FileNotFoundError(f"SRT file not found: '{srt_path}'")
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
            )
        )

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
) -> str:
    """Translate and structurally validate one chunk with bounded retries."""
    print(f"Translating chunk {chunk_number} of {total_chunks}...")
    last_error: Exception | None = None
    instructions = prompt
    for attempt in range(1, _MAX_RETRIES + 1):
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
            response = _request_json(
                "POST",
                "/responses",
                api_key,
                body=request,
            )
            translated = _strip_markdown_fence(_extract_output_text(response))
            _validate_srt_structure(source_chunk, translated)
            return translated
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if isinstance(exc, TranslationFormatError):
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
                time.sleep(_RETRY_DELAY_SECONDS)

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
) -> dict[str, Any]:
    """Send one authenticated JSON request without persisting credentials."""
    payload = (
        json.dumps(body, ensure_ascii=False).encode("utf-8")
        if body is not None
        else None
    )
    request = Request(
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
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        raw_error = exc.read()
        message = _api_error_message(raw_error) or str(exc.reason)
        message = message.replace(api_key, "[redacted]")
        raise OpenAIRequestError(
            f"OpenAI request failed ({exc.code}): {message}"
        ) from exc
    except (URLError, TimeoutError, socket.timeout) as exc:
        reason = getattr(exc, "reason", exc)
        raise OpenAIRequestError(
            f"Could not reach OpenAI: {reason}"
        ) from exc

    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIRequestError("OpenAI returned an invalid JSON response.") from exc
    if not isinstance(decoded, dict):
        raise OpenAIRequestError("OpenAI returned an unexpected response.")
    return decoded


def _extract_output_text(response: dict[str, Any]) -> str:
    """Collect text parts from a completed Responses API payload."""
    if response.get("status") not in {None, "completed"}:
        error = response.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "The response did not complete.")
        else:
            message = "The response did not complete."
        raise OpenAIRequestError(message)

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
    source_cues = _SRT_BLOCK_RE.findall(source.replace("\r\n", "\n"))
    translated_cues = _SRT_BLOCK_RE.findall(translated.replace("\r\n", "\n"))
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
        source_index, source_timing = source_cue
        translated_index, translated_timing = translated_cue
        if require_indices and source_index != translated_index:
            raise TranslationFormatError(f"Cue number changed at position {position}.")
        if _normalize_timing(source_timing) != _normalize_timing(translated_timing):
            raise TranslationFormatError(f"Timestamp changed at cue {source_index}.")


def _normalize_timing(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace(".", ",")


def _strip_markdown_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1])
    return stripped.strip() + "\n"
