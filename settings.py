"""Local settings and macOS Keychain-backed secret storage."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import keyring
from keyring.errors import KeyringError

import languages
import translation_cost


APP_NAME = "SubtitleTranslator"
KEYCHAIN_SERVICE = "com.danielpberg.SubtitleTranslator"
OPENAI_SECRET = "openai_api_key"
OPEN_SUBTITLES_SECRET = "opensubtitles_api_key"

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
WORKSPACE_DIR = APP_SUPPORT_DIR / "Workspace"
SUBTITLES_DIR = WORKSPACE_DIR / "Subtitles"
CACHE_DIR = WORKSPACE_DIR / "Cache"
LOG_DIR = APP_SUPPORT_DIR / "Logs"
SETTINGS_PATH = APP_SUPPORT_DIR / "settings.json"
LEGACY_SETTINGS_PATH = Path.home() / ".animesub_config.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 4,
    "media_locations": [],
    "workspace_directory": str(WORKSPACE_DIR),
    "output_mode": "alongside",
    "custom_output_directory": "",
    "cleanup_intermediates": False,
    "open_output_after_completion": False,
    "target_language": "vi",
    "source_language": "auto",
    "translation_model": "gpt-5.6-luna",
    "reasoning_effort": "low",
    "quality_preset": "custom",
    "prompt_overrides": {},
    "mpv_path": "",
    "interface_language": "system",
    "theme": "system",
}

_SECRET_ENVIRONMENT = {
    OPENAI_SECRET: "OPENAI_API_KEY",
    OPEN_SUBTITLES_SECRET: "OPEN_SUBTITLES_API_KEY",
}


class SecretStorageError(RuntimeError):
    """Raised when a credential cannot be safely stored in macOS Keychain."""


class SettingsStore:
    """Persist non-secret preferences in Application Support."""

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        """Return validated settings merged over application defaults."""
        settings = deepcopy(DEFAULT_SETTINGS)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return settings
        if not isinstance(loaded, dict):
            return settings

        for key in DEFAULT_SETTINGS:
            if key in loaded and _compatible_type(loaded[key], DEFAULT_SETTINGS[key]):
                settings[key] = loaded[key]

        return _validated_settings(settings)

    def save(self, settings: dict[str, Any]) -> None:
        """Write only recognized, non-secret preferences with private permissions."""
        payload = deepcopy(DEFAULT_SETTINGS)
        for key in payload:
            if key in settings and _compatible_type(settings[key], payload[key]):
                payload[key] = settings[key]

        payload = _validated_settings(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_private_directory(self.path.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def update(self, **changes: Any) -> dict[str, Any]:
        """Merge and save preference changes."""
        settings = self.load()
        settings.update(changes)
        self.save(settings)
        return settings

    def remember_media_location(self, directory: str | Path) -> dict[str, Any]:
        """Add a user-selected media directory without scanning anything else."""
        resolved = str(Path(directory).expanduser().resolve())
        settings = self.load()
        locations = [item for item in settings["media_locations"] if item != resolved]
        settings["media_locations"] = [resolved, *locations][:12]
        self.save(settings)
        return settings


class SecretStore:
    """Read and write API credentials using the operating system keychain."""

    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service
        self._cache: dict[str, str] = {}

    def get(self, name: str) -> str:
        """Return an environment override or Keychain value."""
        env_name = _SECRET_ENVIRONMENT.get(name)
        if env_name:
            env_value = os.environ.get(env_name, "").strip()
            if env_value:
                return env_value
        if name in self._cache:
            return self._cache[name]
        try:
            value = (keyring.get_password(self.service, name) or "").strip()
        except KeyringError as exc:
            raise SecretStorageError(
                "macOS Keychain could not be read. No credential was copied "
                "to a settings file."
            ) from exc
        self._cache[name] = value
        return value

    def set(self, name: str, value: str) -> None:
        """Store or remove one credential without writing it to disk ourselves."""
        value = value.strip()
        try:
            if value:
                keyring.set_password(self.service, name, value)
            else:
                try:
                    keyring.delete_password(self.service, name)
                except keyring.errors.PasswordDeleteError:
                    pass
        except KeyringError as exc:
            raise SecretStorageError(
                "macOS Keychain rejected the credential. It was not saved."
            ) from exc
        self._cache[name] = value

    def delete(self, name: str) -> None:
        """Remove one credential from Keychain."""
        self.set(name, "")


def ensure_private_directories(workspace_directory: str | Path | None = None) -> None:
    """Create application directories with user-only permissions."""
    workspace = Path(workspace_directory or WORKSPACE_DIR).expanduser()
    for directory in (APP_SUPPORT_DIR, workspace, workspace / "Subtitles", workspace / "Cache", LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        _chmod_private_directory(directory)


def migrate_legacy_credentials(
    secret_store: SecretStore,
    legacy_path: Path = LEGACY_SETTINGS_PATH,
) -> bool:
    """Move plaintext credentials from the legacy file into Keychain once.

    Each plaintext credential is removed immediately after it is stored
    successfully. Non-secret legacy preferences are intentionally not imported
    because their path assumptions do not belong in the public app.
    """
    legacy_path = Path(legacy_path)
    try:
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(payload, dict):
        return False

    discovered = {
        OPENAI_SECRET: str(payload.get(OPENAI_SECRET, "")).strip(),
        OPEN_SUBTITLES_SECRET: str(payload.get(OPEN_SUBTITLES_SECRET, "")).strip(),
    }
    discovered = {key: value for key, value in discovered.items() if value}
    if not discovered:
        return False

    for key, value in discovered.items():
        secret_store.set(key, value)
        payload.pop(key, None)
        try:
            if payload:
                _write_private_json(legacy_path, payload)
            else:
                legacy_path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecretStorageError(
                "A credential reached Keychain, but its plaintext copy could "
                "not be removed. Delete the legacy settings file manually "
                "before sharing diagnostics."
            ) from exc
    return True


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write a private JSON file beside its existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _compatible_type(value: Any, default: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    return isinstance(value, type(default))


def _validated_settings(values: dict[str, Any]) -> dict[str, Any]:
    """Normalize persisted values before they reach pipeline or UI controls."""
    result = deepcopy(values)
    supported_languages = {profile.code for profile in languages.all_languages()}
    result["version"] = DEFAULT_SETTINGS["version"]

    locations: list[str] = []
    for item in result.get("media_locations", []):
        if not isinstance(item, str) or not item.strip():
            continue
        normalized = str(Path(item).expanduser())
        if normalized not in locations:
            locations.append(normalized)
    result["media_locations"] = locations[:12]

    if result.get("target_language") not in supported_languages:
        result["target_language"] = DEFAULT_SETTINGS["target_language"]
    if result.get("source_language") not in {"auto", *supported_languages}:
        result["source_language"] = DEFAULT_SETTINGS["source_language"]
    if result.get("interface_language") not in {"system", *supported_languages}:
        result["interface_language"] = DEFAULT_SETTINGS["interface_language"]
    if result.get("reasoning_effort") not in {
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        result["reasoning_effort"] = DEFAULT_SETTINGS["reasoning_effort"]
    if result.get("quality_preset") not in {
        "economy",
        "balanced",
        "best",
        "custom",
    }:
        result["quality_preset"] = DEFAULT_SETTINGS["quality_preset"]
    if result.get("output_mode") not in {"alongside", "custom"}:
        result["output_mode"] = DEFAULT_SETTINGS["output_mode"]
    if result.get("theme") not in {"system", "light", "dark"}:
        result["theme"] = DEFAULT_SETTINGS["theme"]

    for key in (
        "workspace_directory",
        "translation_model",
    ):
        value = str(result.get(key, "")).strip()
        result[key] = value or DEFAULT_SETTINGS[key]

    matching_preset = translation_cost.preset_for(
        result["translation_model"],
        result["reasoning_effort"],
    )
    if result["quality_preset"] != "custom":
        result["quality_preset"] = matching_preset

    overrides: dict[str, str] = {}
    raw_overrides = result.get("prompt_overrides", {})
    if isinstance(raw_overrides, dict):
        for key, value in raw_overrides.items():
            if key not in supported_languages or not isinstance(value, str):
                continue
            valid, _message = languages.validate_prompt_template(value)
            if valid:
                overrides[key] = value
    result["prompt_overrides"] = overrides
    return result


def _chmod_private_directory(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass
