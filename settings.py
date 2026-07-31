"""Local settings and macOS Keychain-backed secret storage."""

from __future__ import annotations

import ctypes
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
    "version": 5,
    "media_locations": [],
    "recent_media_files": [],
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
        try:
            loaded_version = int(loaded.get("version", 0))
        except (TypeError, ValueError):
            loaded_version = 0
        if loaded_version < 5:
            settings["media_locations"] = _migrate_legacy_media_locations(
                loaded.get("media_locations", [])
            )
            settings["recent_media_files"] = []
        settings["version"] = DEFAULT_SETTINGS["version"]

        return _validated_settings(settings)

    def save(self, settings: dict[str, Any]) -> None:
        """Write only recognized, non-secret preferences with private permissions."""
        payload = deepcopy(DEFAULT_SETTINGS)
        for key in payload:
            if key in settings and _compatible_type(settings[key], payload[key]):
                payload[key] = settings[key]

        payload["version"] = DEFAULT_SETTINGS["version"]
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

    def add_media_location(self, directory: str | Path) -> dict[str, Any]:
        """Add an explicitly approved directory to the recursive scan roots."""
        resolved = str(Path(directory).expanduser().resolve())
        settings = self.load()
        locations = [item for item in settings["media_locations"] if item != resolved]
        settings["media_locations"] = [resolved, *locations][:12]
        self.save(settings)
        return settings

    def remember_media_location(self, directory: str | Path) -> dict[str, Any]:
        """Backward-compatible alias for explicitly approving a media folder."""
        return self.add_media_location(directory)

    def remember_media_file(self, path: str | Path) -> dict[str, Any]:
        """Remember one selected media file without approving its parent scan."""
        resolved = str(Path(path).expanduser().resolve())
        settings = self.load()
        files = [
            item
            for item in settings["recent_media_files"]
            if item != resolved
        ]
        settings["recent_media_files"] = [resolved, *files][:40]
        self.save(settings)
        return settings


class SecretStore:
    """Read and write API credentials using the operating system keychain."""

    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service
        self._cache: dict[str, str] = {}
        self._presence: dict[str, bool] = {}

    def has(self, name: str) -> bool:
        """Check credential metadata without requesting the secret value."""
        env_name = _SECRET_ENVIRONMENT.get(name)
        if env_name and os.environ.get(env_name, "").strip():
            return True
        if name in self._cache:
            return bool(self._cache[name])
        return self.has_keychain_item(name)

    def has_keychain_item(self, name: str) -> bool:
        """Check whether Keychain itself contains a credential item."""
        if name in self._presence:
            return self._presence[name]
        try:
            present = _keychain_item_exists(self.service, name)
        except KeyringError as exc:
            raise SecretStorageError(
                "macOS Keychain metadata could not be checked."
            ) from exc
        self._presence[name] = present
        return present

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
        self._presence[name] = bool(value)
        return value

    def set(self, name: str, value: str) -> None:
        """Store or remove one credential without writing it to disk ourselves."""
        value = value.strip()
        try:
            if value:
                _set_keychain_password(self.service, name, value)
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
        self._presence[name] = bool(value)

    def delete(self, name: str) -> None:
        """Remove one credential from Keychain."""
        self.set(name, "")


def ensure_private_directories(workspace_directory: str | Path | None = None) -> None:
    """Create application directories with user-only permissions."""
    workspace = Path(workspace_directory or WORKSPACE_DIR).expanduser()
    for directory in (APP_SUPPORT_DIR, workspace, workspace / "Subtitles", workspace / "Cache", LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        _chmod_private_directory(directory)


def reconcile_legacy_credentials(
    secret_store: SecretStore,
    legacy_path: Path = LEGACY_SETTINGS_PATH,
) -> bool:
    """Remove plaintext copies only when matching Keychain items already exist."""
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

    removed = False
    for key in discovered:
        if secret_store.has_keychain_item(key):
            payload.pop(key, None)
            removed = True

    if removed:
        _replace_or_remove_legacy_file(legacy_path, payload)
    else:
        os.chmod(legacy_path, stat.S_IRUSR | stat.S_IWUSR)
    return removed


def remove_legacy_credential(
    name: str,
    legacy_path: Path = LEGACY_SETTINGS_PATH,
) -> None:
    """Remove one plaintext legacy copy after an explicit Keychain save."""
    legacy_path = Path(legacy_path)
    try:
        payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(payload, dict) or name not in payload:
        return
    payload.pop(name, None)
    _replace_or_remove_legacy_file(legacy_path, payload)


def _replace_or_remove_legacy_file(
    legacy_path: Path,
    payload: dict[str, Any],
) -> None:
    if payload:
        _write_private_json(legacy_path, payload)
    else:
        legacy_path.unlink(missing_ok=True)


def _keychain_item_exists(service: str, name: str) -> bool:
    """Query a generic-password item's metadata without decrypting its value."""
    from keyring.backends.macOS import api

    query = api.create_query(
        kSecClass=api.k_("kSecClassGenericPassword"),
        kSecMatchLimit=api.k_("kSecMatchLimitOne"),
        kSecAttrService=service,
        kSecAttrAccount=name,
    )
    status = api.SecItemCopyMatching(query, None)
    if status == api.error.item_not_found:
        return False
    try:
        api.Error.raise_for_status(status)
    except api.Error as exc:
        raise KeyringError("Keychain metadata query failed.") from exc
    return True


def _set_keychain_password(service: str, name: str, value: str) -> None:
    """Add or update a generic password without a delete/recreate cycle."""
    from keyring.backends.macOS import api

    encoded = value.encode("utf-8")
    buffer = ctypes.create_string_buffer(encoded)
    cf_data_create = api._found.CFDataCreate
    cf_data_create.restype = ctypes.c_void_p
    cf_data_create.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_long,
    )
    data = cf_data_create(
        None,
        ctypes.cast(buffer, ctypes.c_void_p),
        len(encoded),
    )
    if not data:
        raise KeyringError("Keychain password encoding failed.")

    query = api.create_query(
        kSecClass=api.k_("kSecClassGenericPassword"),
        kSecAttrService=service,
        kSecAttrAccount=name,
    )
    attributes = api.create_query(
        kSecValueData=ctypes.c_void_p(data),
    )
    sec_item_update = api._sec.SecItemUpdate
    sec_item_update.restype = api.OS_status
    sec_item_update.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    status = sec_item_update(query, attributes)
    if status == api.error.item_not_found:
        add_query = api.create_query(
            kSecClass=api.k_("kSecClassGenericPassword"),
            kSecAttrService=service,
            kSecAttrAccount=name,
            kSecValueData=ctypes.c_void_p(data),
        )
        status = api.SecItemAdd(add_query, None)
    try:
        api.Error.raise_for_status(status)
    except api.Error as exc:
        raise KeyringError("Keychain password update failed.") from exc


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

    recent_files: list[str] = []
    for item in result.get("recent_media_files", []):
        if not isinstance(item, str) or not item.strip():
            continue
        normalized = str(Path(item).expanduser())
        if normalized not in recent_files:
            recent_files.append(normalized)
    result["recent_media_files"] = recent_files[:40]

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


def _migrate_legacy_media_locations(values: Any) -> list[str]:
    """Keep only unambiguous broad scan roots from the mixed version-4 list."""
    if not isinstance(values, list):
        return []
    locations: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if candidate not in locations:
            locations.append(candidate)

    approved: list[str] = []
    for candidate in locations:
        for other in locations:
            if other == candidate:
                continue
            try:
                other.relative_to(candidate)
            except ValueError:
                continue
            approved.append(str(candidate))
            break
    return approved[:12]


def _chmod_private_directory(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass
