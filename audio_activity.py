"""Coarse audio activity extraction for subtitle timing validation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import app_paths
import dependencies
from operation_control import CancellationToken, run_process
import subtitle_sync


_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9.]+)")


def extract_activity(
    video_path: str,
    *,
    cache_directory: str | Path | None = None,
    cancellation_token: CancellationToken | None = None,
) -> list[subtitle_sync.CueTiming]:
    """
    Return cached coarse audio activity segments for *video_path*.

    The signal comes from ffmpeg ``silencedetect``. It is not full speech
    recognition, but it is useful as a cheap last-resort guardrail when no
    text or PGS subtitle timing reference exists.
    """
    video = Path(video_path).resolve()
    cache_path = _cache_path(video, cache_directory)
    cached = _read_cache(cache_path, video)
    if cached is not None:
        if cancellation_token:
            cancellation_token.raise_if_cancelled()
        return cached

    duration_ms = _video_duration_ms(
        str(video),
        cancellation_token=cancellation_token,
    )
    output = _run_silencedetect(
        str(video),
        cancellation_token=cancellation_token,
    )
    silence_segments = _parse_silence_segments(output, duration_ms)
    activity_segments = _invert_silence_segments(silence_segments, duration_ms)
    _write_cache(cache_path, video, activity_segments)
    return activity_segments


def _run_silencedetect(
    video_path: str,
    *,
    cancellation_token: CancellationToken | None = None,
) -> str:
    cmd = [
        dependencies.require_tool("ffmpeg"),
        "-hide_banner",
        "-nostats",
        "-i", video_path,
        "-map", "0:a:0",
        "-vn",
        "-af", "silencedetect=noise=-30dB:d=0.35",
        "-f", "null",
        "-",
    ]
    result = run_process(
        cmd,
        cancellation_token=cancellation_token,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg could not scan audio activity:\n{result.stderr.strip()}"
        )
    return result.stderr


def _parse_silence_segments(output: str, duration_ms: int) -> list[subtitle_sync.CueTiming]:
    """Parse ffmpeg silencedetect stderr into silence intervals."""
    segments: list[subtitle_sync.CueTiming] = []
    current_start: int | None = 0 if "silence_start: 0" in output else None

    for line in output.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            current_start = _seconds_to_ms(start_match.group(1))
            continue

        end_match = _SILENCE_END_RE.search(line)
        if end_match and current_start is not None:
            end_ms = _seconds_to_ms(end_match.group(1))
            if end_ms > current_start:
                segments.append(
                    subtitle_sync.CueTiming(
                        max(0, current_start),
                        min(duration_ms, end_ms),
                    )
                )
            current_start = None

    if current_start is not None and current_start < duration_ms:
        segments.append(subtitle_sync.CueTiming(current_start, duration_ms))

    return _merge_segments(segments, max_gap_ms=200)


def _invert_silence_segments(
    silence_segments: list[subtitle_sync.CueTiming],
    duration_ms: int,
) -> list[subtitle_sync.CueTiming]:
    """Return non-silent activity segments from silence intervals."""
    activity: list[subtitle_sync.CueTiming] = []
    cursor = 0
    for silence in sorted(silence_segments, key=lambda item: item.start_ms):
        if silence.start_ms > cursor:
            activity.append(subtitle_sync.CueTiming(cursor, silence.start_ms))
        cursor = max(cursor, silence.end_ms)
    if cursor < duration_ms:
        activity.append(subtitle_sync.CueTiming(cursor, duration_ms))
    return _merge_segments(
        [segment for segment in activity if segment.end_ms - segment.start_ms >= 250],
        max_gap_ms=250,
    )


def _video_duration_ms(
    video_path: str,
    *,
    cancellation_token: CancellationToken | None = None,
) -> int:
    cmd = [
        dependencies.require_tool("ffprobe"),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = run_process(
        cmd,
        cancellation_token=cancellation_token,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe could not read video duration:\n{result.stderr.strip()}"
        )
    try:
        return int(round(float(result.stdout.strip()) * 1000))
    except ValueError as exc:
        raise RuntimeError("ffprobe returned an invalid video duration.") from exc


def _read_cache(
    cache_path: Path,
    video_path: Path,
) -> list[subtitle_sync.CueTiming] | None:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if payload.get("fingerprint") != _fingerprint(video_path):
        return None

    cues: list[subtitle_sync.CueTiming] = []
    for item in payload.get("segments", []):
        try:
            start_ms = int(item["start_ms"])
            end_ms = int(item["end_ms"])
        except (KeyError, TypeError, ValueError):
            return None
        if end_ms > start_ms:
            cues.append(subtitle_sync.CueTiming(start_ms, end_ms))
    return cues


def _write_cache(
    cache_path: Path,
    video_path: Path,
    segments: list[subtitle_sync.CueTiming],
) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fingerprint": _fingerprint(video_path),
            "segments": [
                {"start_ms": segment.start_ms, "end_ms": segment.end_ms}
                for segment in segments
            ],
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def _cache_path(
    video_path: Path,
    cache_directory: str | Path | None = None,
) -> Path:
    digest = hashlib.sha256(str(video_path).encode("utf-8")).hexdigest()
    directory = (
        Path(cache_directory).expanduser()
        if cache_directory
        else app_paths.CACHE_DIR
    )
    return directory / f"audio_activity_{digest}.json"


def _fingerprint(video_path: Path) -> dict[str, int | str]:
    stat = video_path.stat()
    return {
        "path_hash": hashlib.sha256(str(video_path).encode("utf-8")).hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _seconds_to_ms(value: str) -> int:
    return int(round(float(value) * 1000))


def _merge_segments(
    segments: list[subtitle_sync.CueTiming],
    max_gap_ms: int,
) -> list[subtitle_sync.CueTiming]:
    merged: list[subtitle_sync.CueTiming] = []
    for segment in sorted(segments, key=lambda item: (item.start_ms, item.end_ms)):
        if not merged or segment.start_ms > merged[-1].end_ms + max_gap_ms:
            merged.append(segment)
            continue
        previous = merged[-1]
        merged[-1] = subtitle_sync.CueTiming(
            previous.start_ms,
            max(previous.end_ms, segment.end_ms),
        )
    return merged
