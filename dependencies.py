"""Resolve local media tools without assuming one Homebrew architecture."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Dependency:
    """Availability information for one external executable."""

    name: str
    path: str | None
    required: bool
    install_hint: str

    @property
    def available(self) -> bool:
        return bool(self.path)


_INSTALL_HINTS = {
    "ffmpeg": "Install FFmpeg with Homebrew: brew install ffmpeg",
    "ffprobe": "Install FFmpeg with Homebrew: brew install ffmpeg",
    "mkvmerge": "Install MKVToolNix with Homebrew: brew install mkvtoolnix",
    "mpv": "Install mpv with Homebrew: brew install mpv",
}


def resolve_tool(name: str) -> str | None:
    """Locate a bundled, configured, PATH, or Homebrew executable."""
    environment_name = f"SUBTITLE_TRANSLATOR_{name.upper()}_PATH"
    configured = os.environ.get(environment_name, "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    executable = Path(sys.executable).resolve()
    candidates.extend(
        (
            executable.parent / name,
            executable.parent.parent / "Resources" / "bin" / name,
            executable.parent.parent.parent / "Resources" / "bin" / name,
        )
    )

    discovered = shutil.which(name)
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(
        (
            Path("/opt/homebrew/bin") / name,
            Path("/usr/local/bin") / name,
            Path("/usr/bin") / name,
        )
    )
    for candidate in candidates:
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


def require_tool(name: str) -> str:
    """Return an executable path or raise a user-facing dependency error."""
    path = resolve_tool(name)
    if path:
        return path
    raise FileNotFoundError(_INSTALL_HINTS.get(name, f"Install the '{name}' command."))


def dependency_status() -> tuple[Dependency, ...]:
    """Return processing and playback readiness for onboarding."""
    return (
        Dependency("ffmpeg", resolve_tool("ffmpeg"), True, _INSTALL_HINTS["ffmpeg"]),
        Dependency("ffprobe", resolve_tool("ffprobe"), True, _INSTALL_HINTS["ffprobe"]),
        Dependency("mkvmerge", resolve_tool("mkvmerge"), True, _INSTALL_HINTS["mkvmerge"]),
        Dependency("mpv", resolve_tool("mpv"), False, _INSTALL_HINTS["mpv"]),
    )
