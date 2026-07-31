"""Filesystem helpers for user-selected media and private app workspaces."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

import settings as app_settings


DEFAULT_MEDIA_DIR = Path.home() / "Downloads"
MEDIA_DIR = DEFAULT_MEDIA_DIR
WORKSPACE_DIR = app_settings.WORKSPACE_DIR
SUBTITLES_DIR = app_settings.SUBTITLES_DIR
CACHE_DIR = app_settings.CACHE_DIR

# Compatibility output location for callers that do not yet supply a directory.
# The public workflow writes final output alongside the selected source instead.
MERGED_DIR = WORKSPACE_DIR / "Output"
TRANSLATED_DIR = MERGED_DIR
LOG_PATH = app_settings.LOG_DIR / "SubtitleTranslator.log"

VIDEO_EXTENSIONS = (
    ".mkv",
    ".mp4",
    ".m4v",
    ".mov",
    ".avi",
    ".webm",
    ".ts",
    ".m2ts",
)
SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt")
IMAGE_SUBTITLE_EXTENSIONS = (".sub", ".idx", ".sup")
APP_MANAGED_DIRS = (WORKSPACE_DIR,)


def ensure_output_dirs(workspace_directory: str | Path | None = None) -> None:
    """Create private working directories, never media-library folders."""
    workspace = Path(workspace_directory or WORKSPACE_DIR).expanduser()
    app_settings.ensure_private_directories(workspace)


def workspace_subtitles_dir(workspace_directory: str | Path | None = None) -> Path:
    """Return the subtitle workspace for the active settings."""
    workspace = Path(workspace_directory or WORKSPACE_DIR).expanduser()
    app_settings.ensure_private_directories(workspace)
    return workspace / "Subtitles"


def workspace_cache_dir(workspace_directory: str | Path | None = None) -> Path:
    """Return the cache workspace for the active settings."""
    workspace = Path(workspace_directory or WORKSPACE_DIR).expanduser()
    app_settings.ensure_private_directories(workspace)
    return workspace / "Cache"


def find_latest_video(media_dir: str | Path | None = None) -> Path | None:
    """Return the newest likely full-length media file in an approved folder."""
    return find_latest_video_in_media_dir(Path(media_dir or DEFAULT_MEDIA_DIR))


def media_container_for_path(
    path: str | Path,
    media_roots: Iterable[str | Path] | None = None,
) -> Path:
    """Return the release-level directory used to discover sidecar subtitles.

    If a configured media root contains the selected item, the first directory
    below that root is treated as the release container. Otherwise the selected
    file's direct parent is used. Nothing outside these locations is scanned.
    """
    item = Path(path).expanduser().resolve()
    containing_roots: list[Path] = []
    for root_value in media_roots or ():
        root = Path(root_value).expanduser().resolve()
        try:
            item.relative_to(root)
        except ValueError:
            continue
        containing_roots.append(root)

    if not containing_roots:
        return item.parent

    root = max(containing_roots, key=lambda candidate: len(candidate.parts))
    relative = item.relative_to(root)
    if len(relative.parts) <= 1:
        return root
    return root / relative.parts[0]


def iter_files_recursive(
    directory: str | Path,
    *,
    ignored_directories: Iterable[str | Path] = (),
) -> Iterator[Path]:
    """Yield visible, non-symlink files under a user-approved directory."""
    ignored = {
        Path(item).expanduser().resolve()
        for item in (*APP_MANAGED_DIRS, *ignored_directories)
    }
    root = Path(directory).expanduser()
    try:
        root = root.resolve(strict=True)
    except OSError:
        return
    yield from _iter_files_recursive(root, ignored)


def find_latest_video_in_media_dir(media_dir: str | Path) -> Path | None:
    """Find the newest likely media file within one user-approved directory."""
    media_dir = Path(media_dir).expanduser()
    if not media_dir.is_dir():
        return None
    try:
        media_dir = media_dir.resolve(strict=True)
    except OSError:
        return None

    candidates: list[tuple[float, int, int, Path]] = []
    try:
        entries = list(media_dir.iterdir())
    except OSError:
        return None

    for entry in entries:
        if (
            entry.name.startswith(".")
            or entry.is_symlink()
            or _is_app_managed_dir(entry)
        ):
            continue
        try:
            if entry.is_dir():
                video = _best_video_in_directory(entry)
                if video:
                    score = max(_added_time(entry), _modified_time(video))
                    candidates.append(
                        (
                            score,
                            0 if _looks_like_sample(video) else 1,
                            video.stat().st_size,
                            video,
                        )
                    )
            elif _is_video_file(entry):
                candidates.append(
                    (
                        _modified_time(entry),
                        0 if _looks_like_sample(entry) else 1,
                        entry.stat().st_size,
                        entry,
                    )
                )
        except OSError:
            continue

    if not candidates:
        return None
    full_media = [candidate for candidate in candidates if candidate[1]]
    pool = full_media or candidates
    return max(pool, key=lambda item: (item[0], item[2]))[3]


def unique_output_path(
    source_path: str | Path,
    output_directory: str | Path,
    *,
    suffix: str,
    extension: str,
) -> Path:
    """Return a collision-free output path without overwriting user files."""
    source = Path(source_path)
    output_dir = Path(output_directory).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = extension if extension.startswith(".") else f".{extension}"
    initial = output_dir / f"{source.stem}{suffix}{extension}"
    if not initial.exists():
        return initial
    for index in range(2, 10_000):
        candidate = output_dir / f"{source.stem}{suffix} {index}{extension}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not create a unique output filename.")


def _best_video_in_directory(directory: Path) -> Path | None:
    videos = [
        path
        for path in _iter_files_recursive(directory, set(APP_MANAGED_DIRS))
        if _is_video_file(path)
    ]
    if not videos:
        return None
    return max(
        videos,
        key=lambda path: (
            0 if _looks_like_sample(path) else 1,
            path.stat().st_size,
            _modified_time(path),
        ),
    )


def _iter_files_recursive(directory: Path, ignored: set[Path]) -> Iterator[Path]:
    stack = [Path(directory)]
    visited: set[Path] = set()
    while stack:
        current = stack.pop()
        try:
            resolved_current = current.resolve(strict=True)
        except OSError:
            continue
        if resolved_current in visited or not resolved_current.is_dir():
            continue
        visited.add(resolved_current)
        try:
            entries = list(resolved_current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            try:
                if entry.is_dir():
                    resolved_entry = entry.resolve(strict=True)
                    if resolved_entry in ignored:
                        continue
                    stack.append(resolved_entry)
                elif entry.is_file():
                    yield entry
            except OSError:
                continue


def _is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def _is_app_managed_dir(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return any(
            resolved == managed.resolve()
            or managed.resolve() in resolved.parents
            for managed in APP_MANAGED_DIRS
        )
    except OSError:
        return False


def _looks_like_sample(path: Path) -> bool:
    pieces = [path.stem.lower(), *(part.lower() for part in path.parts)]
    return any(piece in {"sample", "samples"} or "sample" in piece for piece in pieces)


def _added_time(path: Path) -> float:
    stat_result = path.stat()
    return float(getattr(stat_result, "st_birthtime", stat_result.st_mtime))


def _modified_time(path: Path) -> float:
    return float(path.stat().st_mtime)
