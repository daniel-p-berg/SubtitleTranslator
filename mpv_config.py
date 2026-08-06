"""Safely manage SubtitleTranslator's isolated block in mpv.conf."""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import languages


BEGIN_MARKER = "# BEGIN SubtitleTranslator dual subtitles"
END_MARKER = "# END SubtitleTranslator dual subtitles"
DEFAULT_PRIMARY_POSITION = 90
DEFAULT_SECONDARY_POSITION = 10
MIN_SUBTITLE_POSITION = 0
MAX_SUBTITLE_POSITION = 100
MANAGED_OPTIONS = {
    "sid",
    "secondary-sid",
    "secondary-sub-pos",
    "secondary-sub-visibility",
    "slang",
    "sub-pos",
}
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "mpv" / "mpv.conf"


@dataclass(frozen=True)
class ConfigPreview:
    """Proposed mpv configuration and any pre-existing option conflicts."""

    path: Path
    current_text: str
    proposed_text: str
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class ConfigWriteResult:
    """Result of an atomic managed-block update."""

    path: Path
    backup_path: Path | None
    conflicts: tuple[str, ...]


def render_managed_block(
    *,
    primary_position: int = DEFAULT_PRIMARY_POSITION,
    secondary_position: int = DEFAULT_SECONDARY_POSITION,
    show_secondary: bool = True,
    auto_select_secondary: bool = True,
    primary_language: str = "en",
    secondary_language: str = "vi",
) -> str:
    """Return the application-owned mpv.conf block."""
    primary = normalize_position(primary_position, DEFAULT_PRIMARY_POSITION)
    secondary = normalize_position(secondary_position, DEFAULT_SECONDARY_POSITION)
    primary_profile = _language_profile(primary_language, "en")
    secondary_profile = _language_profile(secondary_language, "vi")
    language_priority = ",".join(
        dict.fromkeys((primary_profile.mux_code, secondary_profile.mux_code))
    )
    lines = [
        BEGIN_MARKER,
        "# Managed by SubtitleTranslator. Other mpv settings are preserved.",
        f"# Primary subtitle: {primary_profile.name}",
        f"# Secondary subtitle: {secondary_profile.name}",
        f"slang={language_priority}",
        "sid=auto",
        f"sub-pos={primary}",
        f"secondary-sub-pos={secondary}",
        f"secondary-sub-visibility={'yes' if show_secondary else 'no'}",
    ]
    if auto_select_secondary:
        lines.append("secondary-sid=auto")
    lines.append(END_MARKER)
    return "\n".join(lines)


def preview_configuration(
    *,
    path: str | Path | None = None,
    primary_position: int = DEFAULT_PRIMARY_POSITION,
    secondary_position: int = DEFAULT_SECONDARY_POSITION,
    show_secondary: bool = True,
    auto_select_secondary: bool = True,
    primary_language: str = "en",
    secondary_language: str = "vi",
) -> ConfigPreview:
    """Preview a non-destructive managed-block merge."""
    config_path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    try:
        current = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    block = render_managed_block(
        primary_position=primary_position,
        secondary_position=secondary_position,
        show_secondary=show_secondary,
        auto_select_secondary=auto_select_secondary,
        primary_language=primary_language,
        secondary_language=secondary_language,
    )
    conflicts = _find_conflicts(current)
    return ConfigPreview(
        config_path,
        current,
        _replace_managed_block(current, block),
        conflicts,
    )


def apply_configuration(**options: object) -> ConfigWriteResult:
    """Back up an existing config, then atomically merge the managed block."""
    preview = preview_configuration(**options)
    path = preview.path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, stat.S_IRWXU)
    except OSError:
        pass

    backup: Path | None = None
    mode = stat.S_IRUSR | stat.S_IWUSR
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.backup-{stamp}")
        counter = 2
        while backup.exists():
            backup = path.with_name(
                f"{path.name}.backup-{stamp}-{counter}"
            )
            counter += 1
        shutil.copy2(path, backup)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".mpv.conf.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(preview.proposed_text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return ConfigWriteResult(path, backup, preview.conflicts)


def normalize_position(value: object, default: int) -> int:
    """Return one on-screen mpv subtitle position from 0 through 100."""
    try:
        position = int(value)
    except (TypeError, ValueError):
        position = default
    return min(MAX_SUBTITLE_POSITION, max(MIN_SUBTITLE_POSITION, position))


def _language_profile(value: object, default: str) -> languages.LanguageProfile:
    try:
        return languages.get_language(str(value))
    except KeyError:
        return languages.get_language(default)


def latest_backup(path: str | Path | None = None) -> Path | None:
    """Return the newest backup created beside the selected config."""
    config_path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    backups = sorted(
        config_path.parent.glob(f"{config_path.name}.backup-*"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    return backups[0] if backups else None


def restore_backup(
    backup_path: str | Path,
    *,
    path: str | Path | None = None,
) -> Path:
    """Atomically restore one known backup over mpv.conf."""
    backup = Path(backup_path).expanduser()
    if not backup.is_file():
        raise FileNotFoundError(f"mpv backup not found: {backup}")
    config_path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".mpv.conf.restore.",
        suffix=".tmp",
        dir=config_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(backup, temporary)
        os.replace(temporary, config_path)
    finally:
        temporary.unlink(missing_ok=True)
    return config_path


def managed_config_present(path: str | Path | None = None) -> bool:
    """Return whether the complete managed block is installed."""
    config_path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return BEGIN_MARKER in text and END_MARKER in text


def _replace_managed_block(current: str, block: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(BEGIN_MARKER)}\n.*?"
        rf"^{re.escape(END_MARKER)}[ \t]*(?:\n|$)"
    )
    normalized = _disable_conflicting_options(
        current.replace("\r\n", "\n")
    )
    if pattern.search(normalized):
        merged = pattern.sub(block + "\n", normalized, count=1)
    else:
        prefix = normalized.rstrip()
        merged = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    return merged


def _disable_conflicting_options(text: str) -> str:
    """Comment out active managed options outside the application block."""
    outside_block = True
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == BEGIN_MARKER:
            outside_block = False
        if outside_block and stripped and not stripped.startswith("#"):
            option = stripped.split("=", 1)[0].strip().lstrip("-")
            if option in MANAGED_OPTIONS:
                indentation = line[: len(line) - len(line.lstrip())]
                line = (
                    f"{indentation}# SubtitleTranslator disabled conflicting "
                    f"option: {line.lstrip()}"
                )
        lines.append(line)
        if stripped == END_MARKER:
            outside_block = True
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def _find_conflicts(current: str) -> tuple[str, ...]:
    outside = _without_managed_block(current)
    conflicts: list[str] = []
    for line in outside.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        option = stripped.split("=", 1)[0].strip().lstrip("-")
        if option in MANAGED_OPTIONS and option not in conflicts:
            conflicts.append(option)
    return tuple(conflicts)


def _without_managed_block(text: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(BEGIN_MARKER)}\n.*?"
        rf"^{re.escape(END_MARKER)}[ \t]*(?:\n|$)"
    )
    return pattern.sub("", text.replace("\r\n", "\n"))
