"""Transactionally remux media with clean, language-labelled subtitle tracks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import app_paths
import dependencies
import languages


_MIN_SPACE_RESERVE = 512 * 1024 * 1024


@dataclass(frozen=True)
class SubtitleTrack:
    """One clean text subtitle to add to a media container."""

    path: str
    language_code: str
    title: str = ""
    default: bool = False

    @property
    def language(self) -> languages.LanguageProfile:
        return languages.get_language(self.language_code)


def mux_tracks(
    video_path: str,
    tracks: list[SubtitleTrack],
    *,
    output_directory: str | Path | None = None,
    suffix: str = " [Subtitled]",
) -> str:
    """Create a verified MKV beside the source or in a chosen output folder.

    Video and audio are stream-copied. Existing subtitle streams are omitted
    and replaced by the explicitly selected clean tracks, preventing duplicate
    or positioned subtitle tracks from interfering with mpv.
    """
    source = Path(video_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Media file not found: {source}")
    if not tracks:
        raise ValueError("At least one subtitle track is required for merging.")

    normalized_tracks = _validate_tracks(tracks)
    destination = (
        Path(output_directory).expanduser()
        if output_directory
        else source.parent
    )
    output_path = app_paths.unique_output_path(
        source,
        destination,
        suffix=suffix,
        extension=".mkv",
    )
    partial_path = output_path.with_name(f".{output_path.stem}.partial.mkv")

    destination.mkdir(parents=True, exist_ok=True)
    _ensure_free_space(source, destination)
    partial_path.unlink(missing_ok=True)
    try:
        _run_mkvmerge(source, normalized_tracks, partial_path)
        _verify_mux_output(source, partial_path, normalized_tracks)
        os.replace(partial_path, output_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    print(f"Output written to: {output_path}")
    return str(output_path)


def mux_subtitles(
    video_path: str,
    english_srt: str | None,
    vietnamese_srt: str,
) -> str:
    """Backward-compatible English/Vietnamese merge wrapper."""
    tracks = [
        SubtitleTrack(
            vietnamese_srt,
            "vi",
            languages.get_language("vi").name,
            True,
        )
    ]
    if english_srt:
        tracks.append(
            SubtitleTrack(
                english_srt,
                "en",
                languages.get_language("en").name,
                False,
            )
        )
    return mux_tracks(
        video_path,
        tracks,
        output_directory=app_paths.MERGED_DIR,
        suffix="_subbed",
    )


def probe_media(path: str | Path) -> dict:
    """Return ffprobe format and stream metadata."""
    ffprobe = dependencies.require_tool("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe could not inspect '{path}':\n{result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid data for '{path}'.") from exc


def media_duration_seconds(path: str | Path) -> float:
    """Return the container duration or raise a clear validation error."""
    duration = _format_duration_seconds(probe_media(path))
    if duration is None:
        raise RuntimeError(f"Media duration could not be read for '{path}'.")
    return duration


def _run_mkvmerge(
    source: Path,
    tracks: list[SubtitleTrack],
    output_path: Path,
) -> None:
    mkvmerge = dependencies.require_tool("mkvmerge")
    command = [
        mkvmerge,
        "--output",
        str(output_path),
        "--no-subtitles",
        str(source),
    ]
    for track in tracks:
        profile = track.language
        command.extend(
            [
                "--language",
                f"0:{profile.mux_code}",
                "--track-name",
                f"0:{track.title or profile.name}",
                "--default-track-flag",
                f"0:{'yes' if track.default else 'no'}",
                "--forced-display-flag",
                "0:no",
                str(Path(track.path).expanduser().resolve()),
            ]
        )

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode >= 2:
        raise RuntimeError(
            f"mkvmerge failed while processing '{source.name}':\n"
            f"{result.stdout.strip()}\n{result.stderr.strip()}"
        )
    if result.returncode == 1:
        print(f"mkvmerge completed with warnings:\n{result.stdout.strip()}")


def _validate_tracks(tracks: list[SubtitleTrack]) -> list[SubtitleTrack]:
    normalized: list[SubtitleTrack] = []
    seen: set[tuple[Path, str]] = set()
    for track in tracks:
        path = Path(track.path).expanduser().resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Subtitle file not found or empty: {path}")
        profile = languages.get_language(track.language_code)
        key = (path, profile.code)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            SubtitleTrack(
                str(path),
                profile.code,
                track.title or profile.name,
                track.default,
            )
        )
    if not any(track.default for track in normalized):
        first = normalized[0]
        normalized[0] = SubtitleTrack(
            first.path,
            first.language_code,
            first.title,
            True,
        )
    return normalized


def _ensure_free_space(
    source: str | Path,
    output_directory: str | Path,
) -> None:
    source = Path(source)
    output_directory = Path(output_directory)
    source_size = source.stat().st_size
    reserve = max(_MIN_SPACE_RESERVE, int(source_size * 0.05))
    required = source_size + reserve
    free = shutil.disk_usage(output_directory).free
    if free < required:
        raise RuntimeError(
            "Not enough free disk space to merge safely. "
            f"Need about {_format_bytes(required)}, but only "
            f"{_format_bytes(free)} is available."
        )
    print(
        f"Merge preflight passed: {_format_bytes(free)} free, "
        f"{_format_bytes(required)} required."
    )


def _verify_mux_output(
    source: Path,
    output: Path,
    expected_tracks: list[SubtitleTrack],
) -> None:
    if not output.is_file():
        raise RuntimeError("Merge verification failed: output was not created.")
    minimum_size = max(64 * 1024, int(source.stat().st_size * 0.50))
    if output.stat().st_size < minimum_size:
        raise RuntimeError(
            "Merge verification failed: output is unexpectedly small "
            f"({_format_bytes(output.stat().st_size)})."
        )

    source_data = probe_media(source)
    output_data = probe_media(output)
    source_duration = _format_duration_seconds(source_data)
    output_duration = _format_duration_seconds(output_data)
    if source_duration is None or output_duration is None:
        raise RuntimeError("Merge verification failed: duration could not be read.")
    tolerance = max(5.0, source_duration * 0.005)
    if abs(output_duration - source_duration) > tolerance:
        raise RuntimeError(
            "Merge verification failed: output duration differs from the source "
            f"by {output_duration - source_duration:+.1f}s."
        )

    subtitle_streams = [
        stream
        for stream in output_data.get("streams", [])
        if stream.get("codec_type") == "subtitle"
    ]
    if len(subtitle_streams) < len(expected_tracks):
        raise RuntimeError(
            "Merge verification failed: expected "
            f"{len(expected_tracks)} subtitle track(s), found "
            f"{len(subtitle_streams)}."
        )
    actual_languages = {
        str((stream.get("tags") or {}).get("language", "")).lower()
        for stream in subtitle_streams
    }
    for track in expected_tracks:
        profile = track.language
        if not actual_languages & {
            profile.code.lower(),
            profile.opensubtitles_code.lower(),
            profile.mux_code.lower(),
        }:
            raise RuntimeError(
                f"Merge verification failed: {profile.name} track is missing."
            )
    print(
        f"Merge verification passed: {output_duration:.1f}s, "
        f"{len(subtitle_streams)} subtitle track(s)."
    )


def _format_duration_seconds(probe_data: dict) -> float | None:
    try:
        return float((probe_data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        return None


def _format_bytes(value: int) -> str:
    gib = value / (1024**3)
    if gib >= 1:
        return f"{gib:.1f} GB"
    return f"{value / (1024**2):.0f} MB"
