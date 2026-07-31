"""Resolve local media tools without assuming one Homebrew architecture."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


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

_HOMEBREW_FORMULAS = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
    "mkvmerge": "mkvtoolnix",
    "mpv": "mpv",
}


def resolve_homebrew() -> str | None:
    """Locate Homebrew on either supported macOS architecture."""
    configured = os.environ.get("SUBTITLE_TRANSLATOR_HOMEBREW_PATH", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    discovered = shutil.which("brew")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(
        (
            Path("/opt/homebrew/bin/brew"),
            Path("/usr/local/bin/brew"),
        )
    )
    for candidate in candidates:
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


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


def required_tools_ready() -> bool:
    """Return whether every processing dependency is currently available."""
    return all(item.available for item in dependency_status() if item.required)


def homebrew_formulae_for_tools(tool_names: Iterable[str]) -> tuple[str, ...]:
    """Map executable names to a stable, de-duplicated Homebrew install plan."""
    formulae: list[str] = []
    for name in tool_names:
        try:
            formula = _HOMEBREW_FORMULAS[name]
        except KeyError as exc:
            raise ValueError(f"Unsupported local tool: {name}") from exc
        if formula not in formulae:
            formulae.append(formula)
    return tuple(formulae)


def missing_homebrew_formulae(*, include_optional: bool = False) -> tuple[str, ...]:
    """Return formulae needed for missing required tools and optional mpv."""
    missing = (
        item.name
        for item in dependency_status()
        if not item.available and (item.required or include_optional)
    )
    return homebrew_formulae_for_tools(missing)


def homebrew_install_command(
    formulae: Iterable[str],
    *,
    executable: str | None = None,
) -> str:
    """Build the exact command shown to and approved by the user."""
    requested = tuple(formulae)
    unsupported = set(requested) - set(_HOMEBREW_FORMULAS.values())
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"Unsupported Homebrew formula: {names}")
    if not requested:
        raise ValueError("No Homebrew formulae were requested.")

    brew = executable or resolve_homebrew()
    if not brew:
        raise FileNotFoundError(
            "Homebrew is not installed. Use the official Homebrew installer first."
        )
    return shlex.join((brew, "install", *requested))


def launch_homebrew_install(formulae: Iterable[str]) -> str:
    """Open a visible Terminal tab containing the approved install command."""
    command = homebrew_install_command(formulae)
    script = (
        "on run argv\n"
        'tell application "Terminal"\n'
        "activate\n"
        "do script (item 1 of argv)\n"
        "end tell\n"
        "end run"
    )
    completed = subprocess.run(
        ["/usr/bin/osascript", "-e", script, command],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "macOS could not open Terminal."
        raise RuntimeError(detail)
    return command
