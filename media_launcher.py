"""Discover media files and launch them in the user's real mpv installation."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import app_paths
import dependencies


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
    try:
        process = subprocess.Popen(
            [executable, "--", str(media)],
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


def recent_merged_files(limit: int = 6, directory: Path | None = None) -> list[Path]:
    """Backward-compatible recent-output helper."""
    root = Path(directory) if directory is not None else app_paths.MERGED_DIR
    return recent_media_files([root], limit=limit)


def recent_media_files(
    directories: list[str | Path],
    *,
    limit: int = 12,
) -> list[Path]:
    """Return recent playable files from user-approved locations."""
    if limit <= 0:
        return []

    candidates: list[tuple[float, int, Path]] = []
    seen: set[Path] = set()
    for directory in directories:
        root = Path(directory).expanduser()
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in PLAYABLE_EXTENSIONS:
                continue
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                stat = path.stat()
            except OSError:
                continue
            candidates.append((stat.st_mtime, stat.st_size, path))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [path for _mtime, _size, path in candidates[:limit]]
