"""Structured, redacted local diagnostics for user-controlled export."""

from __future__ import annotations

import json
import os
import platform
import re
import stat
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import dependencies


SCHEMA_VERSION = 1
_SECRET_RE = re.compile(
    r"(?i)\b(?:sk|apikey|api_key|token)[-_]?[A-Za-z0-9]{8,}\b"
)
_HOME_PATH_RE = re.compile(
    r"(?:/Users/|/home/)[^/\s'\"<>]+(?:/[^\s'\"<>]+)*"
)


class DiagnosticsRecorder:
    """Collect metadata-only events without subtitle text or credentials."""

    def __init__(
        self,
        *,
        app_version: str,
        operation: str,
        media_path: str = "",
    ) -> None:
        self._lock = threading.Lock()
        self._app_version = app_version
        self._operation = operation
        self._media_filename = Path(media_path).name if media_path else ""
        self._started_at = _utc_now()
        self._events: list[dict[str, Any]] = []
        self._summary: dict[str, Any] = {}

    def record(
        self,
        category: str,
        action: str,
        *,
        status: str = "info",
        **details: Any,
    ) -> None:
        event = {
            "time": _utc_now(),
            "category": category,
            "action": action,
            "status": status,
            "details": _sanitize(details),
        }
        with self._lock:
            self._events.append(event)

    def update_summary(self, **values: Any) -> None:
        with self._lock:
            self._summary.update(_sanitize(values))

    def report(self, *, include_tools: bool = False) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)
            summary = dict(self._summary)
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "app": {
                "name": "SubtitleTranslator",
                "version": self._app_version,
            },
            "privacy": {
                "redacted": True,
                "contains_subtitle_text": False,
                "contains_api_credentials": False,
                "contains_full_media_paths": False,
            },
            "system": {
                "os": platform.platform(),
                "architecture": platform.machine(),
                "python": platform.python_version(),
            },
            "operation": {
                "name": self._operation,
                "media_filename": self._media_filename,
                "started_at": self._started_at,
                "generated_at": _utc_now(),
                "summary": summary,
                "events": events,
            },
        }
        if include_tools:
            report["tools"] = collect_tool_versions()
        return _sanitize(report)


def collect_tool_versions() -> list[dict[str, Any]]:
    """Collect bounded, non-sensitive version lines for local tools."""
    tools: list[dict[str, Any]] = []
    for item in dependencies.dependency_status():
        entry: dict[str, Any] = {
            "name": item.name,
            "available": item.available,
        }
        if item.path:
            entry["location"] = _location_kind(Path(item.path))
            try:
                completed = subprocess.run(  # noqa: S603
                    [item.path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                output = completed.stdout.strip() or completed.stderr.strip()
                entry["version"] = output.splitlines()[0][:240] if output else ""
            except (OSError, subprocess.SubprocessError):
                entry["version"] = "unavailable"
        tools.append(entry)
    return tools


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    """Atomically write a private, redacted diagnostics JSON file."""
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(_sanitize(report), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if any(
                marker in normalized_key.casefold()
                for marker in ("api_key", "apikey", "authorization", "token")
            ):
                cleaned[normalized_key] = "[redacted]"
            else:
                cleaned[normalized_key] = _sanitize(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, Path):
        return value.name
    if isinstance(value, str):
        text = _SECRET_RE.sub("[redacted]", value)
        text = _HOME_PATH_RE.sub("<local-path>", text)
        return text[:4000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize(str(value))


def _location_kind(path: Path) -> str:
    text = str(path)
    if "/Cellar/" in text or text.startswith(("/opt/homebrew/", "/usr/local/")):
        return "Homebrew"
    if text.startswith("/usr/"):
        return "system"
    if ".app/Contents/" in text:
        return "application bundle"
    return "custom"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
