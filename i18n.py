"""Qt-native interface localization and locale metadata."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QLibraryInfo,
    QLocale,
    Qt,
    QTranslator,
)
from PySide6.QtWidgets import QApplication


CONTEXT = "SubtitleTranslator"


@dataclass(frozen=True)
class InterfaceLanguage:
    """One interface locale shipped with the application."""

    code: str
    english_name: str
    native_name: str
    rtl: bool = False
    qt_locale: str = ""

    @property
    def display_name(self) -> str:
        if self.native_name == self.english_name:
            return self.english_name
        return f"{self.native_name} ({self.english_name})"

    @property
    def catalog_name(self) -> str:
        return self.code.replace("-", "_")


INTERFACE_LANGUAGES: tuple[InterfaceLanguage, ...] = (
    InterfaceLanguage("en", "English", "English", qt_locale="en"),
    InterfaceLanguage("vi", "Vietnamese", "Tiếng Việt", qt_locale="vi"),
    InterfaceLanguage("ko", "Korean", "한국어", qt_locale="ko"),
    InterfaceLanguage("ja", "Japanese", "日本語", qt_locale="ja"),
    InterfaceLanguage(
        "zh-Hans",
        "Chinese (Simplified)",
        "简体中文",
        qt_locale="zh_CN",
    ),
    InterfaceLanguage(
        "zh-Hant",
        "Chinese (Traditional)",
        "繁體中文",
        qt_locale="zh_TW",
    ),
    InterfaceLanguage("es", "Spanish", "Español", qt_locale="es"),
    InterfaceLanguage(
        "pt-BR",
        "Portuguese (Brazil)",
        "Português (Brasil)",
        qt_locale="pt_BR",
    ),
    InterfaceLanguage(
        "pt-PT",
        "Portuguese (Portugal)",
        "Português (Portugal)",
        qt_locale="pt_PT",
    ),
    InterfaceLanguage("fr", "French", "Français", qt_locale="fr"),
    InterfaceLanguage("de", "German", "Deutsch", qt_locale="de"),
    InterfaceLanguage("it", "Italian", "Italiano", qt_locale="it"),
    InterfaceLanguage("ru", "Russian", "Русский", qt_locale="ru"),
    InterfaceLanguage("uk", "Ukrainian", "Українська", qt_locale="uk"),
    InterfaceLanguage("pl", "Polish", "Polski", qt_locale="pl"),
    InterfaceLanguage("nl", "Dutch", "Nederlands", qt_locale="nl"),
    InterfaceLanguage("tr", "Turkish", "Türkçe", qt_locale="tr"),
    InterfaceLanguage("ar", "Arabic", "العربية", rtl=True, qt_locale="ar"),
    InterfaceLanguage("fa", "Persian", "فارسی", rtl=True, qt_locale="fa"),
    InterfaceLanguage("he", "Hebrew", "עברית", rtl=True, qt_locale="he"),
    InterfaceLanguage("hi", "Hindi", "हिन्दी", qt_locale="hi"),
    InterfaceLanguage("bn", "Bengali", "বাংলা", qt_locale="bn"),
    InterfaceLanguage("ur", "Urdu", "اردو", rtl=True, qt_locale="ur"),
    InterfaceLanguage(
        "id",
        "Indonesian",
        "Bahasa Indonesia",
        qt_locale="id",
    ),
    InterfaceLanguage("ms", "Malay", "Bahasa Melayu", qt_locale="ms"),
    InterfaceLanguage("th", "Thai", "ไทย", qt_locale="th"),
    InterfaceLanguage("fil", "Filipino", "Filipino", qt_locale="fil"),
    InterfaceLanguage("ro", "Romanian", "Română", qt_locale="ro"),
    InterfaceLanguage("cs", "Czech", "Čeština", qt_locale="cs"),
    InterfaceLanguage("el", "Greek", "Ελληνικά", qt_locale="el"),
)

_BY_CODE = {item.code.lower(): item for item in INTERFACE_LANGUAGES}
_installed_translators: list[QTranslator] = []
_active_language = _BY_CODE["en"]


def tr(source: str) -> str:
    """Translate one application string using the installed Qt catalog."""
    return QCoreApplication.translate(CONTEXT, source)


def interface_languages() -> tuple[InterfaceLanguage, ...]:
    """Return every interface language in stable product order."""
    return INTERFACE_LANGUAGES


def get_interface_language(code: str) -> InterfaceLanguage:
    """Return an interface locale, falling back safely to English."""
    return _BY_CODE.get(str(code).lower(), _BY_CODE["en"])


def active_language() -> InterfaceLanguage:
    """Return the locale currently installed in QApplication."""
    return _active_language


def display_name(code: str) -> str:
    """Return a bilingual name that remains recognizable in every locale."""
    return get_interface_language(code).display_name


def match_supported_locale(locale_name: str) -> str | None:
    """Map a macOS/Qt locale identifier to one of the shipped app codes."""
    normalized = locale_name.replace("_", "-").lower()
    if normalized in _BY_CODE:
        return _BY_CODE[normalized].code

    parts = normalized.split("-")
    base = parts[0]
    if base == "zh":
        traditional_markers = {"hant", "tw", "hk", "mo"}
        return (
            "zh-Hant"
            if traditional_markers.intersection(parts[1:])
            else "zh-Hans"
        )
    if base == "pt":
        return "pt-PT" if "pt" in parts[1:] else "pt-BR"
    if base in {"tl", "fil"}:
        return "fil"

    language = _BY_CODE.get(base)
    return language.code if language else None


def system_language_code() -> str:
    """Choose the first supported language from the Mac preference order."""
    for locale_name in QLocale.system().uiLanguages():
        matched = match_supported_locale(locale_name)
        if matched:
            return matched
    matched = match_supported_locale(QLocale.system().name())
    return matched or "en"


def resolve_language(preference: str) -> InterfaceLanguage:
    """Resolve a stored preference, including the special system setting."""
    override = os.environ.get(
        "SUBTITLE_TRANSLATOR_INTERFACE_LANGUAGE",
        "",
    ).strip()
    if override:
        return get_interface_language(override)
    code = system_language_code() if preference == "system" else preference
    return get_interface_language(code)


def translations_directory() -> Path:
    """Return the source or packaged translation resource directory."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / "translations"


def install_translators(
    application: QApplication,
    preference: str,
) -> InterfaceLanguage:
    """Install app and Qt catalogs before constructing any widgets."""
    global _active_language

    for translator in _installed_translators:
        application.removeTranslator(translator)
    _installed_translators.clear()

    language = resolve_language(preference)
    if language.code != "en":
        app_translator = QTranslator(application)
        catalog = (
            translations_directory()
            / f"subtitletranslator_{language.catalog_name}.qm"
        )
        if app_translator.load(str(catalog)):
            application.installTranslator(app_translator)
            _installed_translators.append(app_translator)

        qt_translator = QTranslator(application)
        qt_path = Path(
            QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        )
        if qt_translator.load(f"qtbase_{language.qt_locale}", str(qt_path)):
            application.installTranslator(qt_translator)
            _installed_translators.append(qt_translator)

    direction = (
        Qt.LayoutDirection.RightToLeft
        if language.rtl
        else Qt.LayoutDirection.LeftToRight
    )
    application.setLayoutDirection(direction)
    application.setProperty("interfaceLanguage", language.code)
    QLocale.setDefault(QLocale(language.qt_locale or language.code))
    _active_language = language
    return language
