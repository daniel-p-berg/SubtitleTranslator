"""Discover media files and launch them in the user's real mpv installation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import app_paths
import dependencies
import languages
import mpv_config


PLAYABLE_EXTENSIONS = (
    ".mkv",
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".avi",
    ".ts",
    ".m2ts",
)

_MPV_CANDIDATES = (
    "/opt/homebrew/bin/mpv",
    "/usr/local/bin/mpv",
    "/Applications/mpv.app/Contents/MacOS/mpv",
    "~/Applications/mpv.app/Contents/MacOS/mpv",
)

_IMAGE_SUBTITLE_CODECS = {
    "dvb_subtitle",
    "dvd_subtitle",
    "dvdsub",
    "hdmv_pgs_bitmap",
    "hdmv_pgs_subtitle",
    "pgssub",
    "xsub",
}


class MpvLaunchError(RuntimeError):
    """Raised when a requested media file cannot be launched in mpv."""


@dataclass(frozen=True)
class LaunchInfo:
    """Details about a successfully started mpv process."""

    media_path: str
    executable: str
    pid: int


def resolve_mpv_executable(configured_path: str = "") -> str:
    """Return an executable path for mpv, including Homebrew and app bundles."""
    candidates: list[str] = []
    configured = configured_path.strip() or os.environ.get("MPV_PATH", "").strip()
    if configured:
        candidates.append(configured)

    path_match = dependencies.resolve_tool("mpv") or shutil.which("mpv")
    if path_match:
        candidates.append(path_match)
    candidates.extend(_MPV_CANDIDATES)

    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(Path(candidate).expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        if Path(resolved).is_file() and os.access(resolved, os.X_OK):
            return resolved

    raise MpvLaunchError(
        "mpv was not found. Install it with Homebrew (`brew install mpv`) "
        "or set MPV_PATH to the executable."
    )


def launch_in_mpv(
    media_path: str | Path,
    *,
    configured_path: str = "",
    primary_position: int = mpv_config.DEFAULT_PRIMARY_POSITION,
    secondary_position: int = mpv_config.DEFAULT_SECONDARY_POSITION,
    primary_language: str = "en",
    secondary_language: str = "vi",
    show_secondary: bool = True,
    auto_select_secondary: bool = True,
) -> LaunchInfo:
    """Launch *media_path* in a detached external mpv process."""
    media = Path(media_path).expanduser().resolve()
    if not media.is_file():
        raise MpvLaunchError(f"Media file not found: {media}")
    if media.suffix.lower() not in PLAYABLE_EXTENSIONS:
        raise MpvLaunchError(f"Unsupported media type for launcher: {media.suffix or '(none)'}")

    executable = (
        resolve_mpv_executable(configured_path)
        if configured_path
        else resolve_mpv_executable()
    )
    subtitle_options = _subtitle_role_options(
        media,
        primary_language=primary_language,
        secondary_language=secondary_language,
        auto_select_secondary=auto_select_secondary,
    )
    position_options = _subtitle_position_options(
        primary_position,
        secondary_position,
        show_secondary=show_secondary,
    )
    try:
        process = subprocess.Popen(
            [
                executable,
                *subtitle_options,
                *position_options,
                "--",
                str(media),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        raise MpvLaunchError(f"Could not start mpv: {exc}") from exc

    # Reap the detached child when playback ends without tying it to the GUI.
    threading.Thread(target=process.wait, daemon=True).start()
    return LaunchInfo(str(media), executable, process.pid)


def _subtitle_position_options(
    primary_position: int,
    secondary_position: int,
    *,
    show_secondary: bool = True,
) -> tuple[str, str, str, str, str]:
    primary = mpv_config.normalize_position(
        primary_position,
        mpv_config.DEFAULT_PRIMARY_POSITION,
    )
    secondary = mpv_config.normalize_position(
        secondary_position,
        mpv_config.DEFAULT_SECONDARY_POSITION,
    )
    return (
        f"--sub-margin-y={mpv_config.MPV_SUBTITLE_MARGIN_Y}",
        "--sub-use-margins=yes",
        f"--sub-pos={primary}",
        f"--secondary-sub-pos={secondary}",
        f"--secondary-sub-visibility={'yes' if show_secondary else 'no'}",
    )


def _subtitle_role_options(
    media_path: str | Path,
    *,
    primary_language: str = "en",
    secondary_language: str = "vi",
    auto_select_secondary: bool = True,
) -> tuple[str, str]:
    """Choose explicit MPV primary/secondary IDs when local metadata permits."""
    streams = _probe_subtitle_streams(media_path)
    if streams is None:
        return (
            "--sid=auto",
            "--secondary-sid=auto"
            if auto_select_secondary
            else "--secondary-sid=no",
        )
    if not streams:
        return ("--sid=no", "--secondary-sid=no")

    candidates = [
        {
            "sid": sid,
            "image": (
                str(stream.get("codec_name", "")).lower()
                in _IMAGE_SUBTITLE_CODECS
            ),
            "default": bool(
                (stream.get("disposition") or {}).get("default")
            ),
            "forced": _stream_is_forced(stream),
            "language": _stream_language_code(stream),
        }
        for sid, stream in enumerate(streams, start=1)
    ]
    full = [item for item in candidates if not item["forced"]] or candidates
    images = [item for item in full if item["image"]]
    text = [item for item in full if not item["image"]]

    primary_code = _normalized_language_code(primary_language, "en")
    secondary_code = _normalized_language_code(secondary_language, "vi")
    preferred_primary = [
        item for item in full if item["language"] == primary_code
    ]
    preferred_secondary = [
        item
        for item in text
        if item["language"] == secondary_code
    ]
    if not auto_select_secondary:
        primary_choices = preferred_primary or full
        primary = max(primary_choices, key=_selection_score)
        return (f"--sid={primary['sid']}", "--secondary-sid=no")
    if preferred_primary:
        primary = max(preferred_primary, key=_selection_score)
        secondary_choices = [
            item
            for item in preferred_secondary
            if item["sid"] != primary["sid"]
        ]
        if secondary_choices:
            secondary = max(secondary_choices, key=_selection_score)
            return (
                f"--sid={primary['sid']}",
                f"--secondary-sid={secondary['sid']}",
            )
        return (f"--sid={primary['sid']}", "--secondary-sid=no")

    if preferred_secondary:
        secondary = max(preferred_secondary, key=_selection_score)
        primary_choices = [
            item for item in full if item["sid"] != secondary["sid"]
        ]
        if primary_choices:
            primary = max(primary_choices, key=_selection_score)
            return (
                f"--sid={primary['sid']}",
                f"--secondary-sid={secondary['sid']}",
            )

    if images and text:
        primary = max(images, key=_selection_score)
        secondary = max(text, key=_selection_score)
        return (
            f"--sid={primary['sid']}",
            f"--secondary-sid={secondary['sid']}",
        )

    primary = max(full, key=_selection_score)
    secondary = None
    if text:
        remaining = [item for item in text if item["sid"] != primary["sid"]]
        if remaining:
            secondary = max(remaining, key=_selection_score)
    return (
        f"--sid={primary['sid']}",
        (
            f"--secondary-sid={secondary['sid']}"
            if secondary
            else "--secondary-sid=no"
        ),
    )


def _probe_subtitle_streams(media_path: str | Path) -> list[dict] | None:
    """Return subtitle streams, or None when probing is unavailable."""
    ffprobe = dependencies.resolve_tool("ffprobe") or shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(  # noqa: S603
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                str(Path(media_path).expanduser().resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return [
        stream
        for stream in payload.get("streams", [])
        if stream.get("codec_type") == "subtitle"
    ]


def _stream_is_forced(stream: dict) -> bool:
    disposition = stream.get("disposition") or {}
    if disposition.get("forced"):
        return True
    tags = stream.get("tags") or {}
    title = str(tags.get("title", tags.get("TITLE", ""))).lower()
    return any(
        marker in title
        for marker in ("forced", "signs", "songs", "karaoke")
    )


def _stream_language_code(stream: dict) -> str:
    tags = stream.get("tags") or {}
    profile = languages.identify_language(
        str(tags.get("language", tags.get("LANGUAGE", ""))),
        str(tags.get("title", tags.get("TITLE", ""))),
    )
    return profile.code if profile else "und"


def _normalized_language_code(value: object, default: str) -> str:
    try:
        return languages.get_language(str(value)).code
    except KeyError:
        return default


def _selection_score(item: dict) -> tuple[int, int]:
    return (1 if item["default"] else 0, -int(item["sid"]))


def recent_merged_files(limit: int = 6, directory: Path | None = None) -> list[Path]:
    """Backward-compatible recent-output helper."""
    root = Path(directory) if directory is not None else app_paths.MERGED_DIR
    return recent_media_files([root], limit=limit)


def recent_media_files(
    directories: list[str | Path],
    *,
    files: list[str | Path] | tuple[str | Path, ...] = (),
    limit: int = 12,
) -> list[Path]:
    """Return exact recent files plus media found in approved scan roots."""
    if limit <= 0:
        return []

    candidates: list[tuple[float, int, Path]] = []
    seen: set[Path] = set()

    def add_candidate(path: Path) -> None:
        if path.suffix.lower() not in PLAYABLE_EXTENSIONS:
            return
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return
        if resolved in seen or not resolved.is_file():
            return
        seen.add(resolved)
        try:
            stat = resolved.stat()
        except OSError:
            return
        candidates.append((stat.st_mtime, stat.st_size, resolved))

    for file_path in files:
        add_candidate(Path(file_path).expanduser())

    for directory in directories:
        root = Path(directory).expanduser()
        if not root.is_dir():
            continue
        for path in app_paths.iter_files_recursive(root):
            add_candidate(path)

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [path for _mtime, _size, path in candidates[:limit]]
