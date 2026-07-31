"""SubtitleTranslator macOS application entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import i18n
import settings
from ui import MainWindow, apply_application_style


APP_VERSION = "0.9.0-beta.4"


def main() -> None:
    """Start the Qt application."""
    application = QApplication(sys.argv)
    application.setApplicationName("SubtitleTranslator")
    application.setApplicationDisplayName("SubtitleTranslator")
    application.setOrganizationName("SubtitleTranslator")
    application.setApplicationVersion(APP_VERSION)
    application.setQuitOnLastWindowClosed(True)
    preferences = settings.SettingsStore().load()
    i18n.install_translators(
        application,
        preferences.get("interface_language", "system"),
    )
    icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "app-icon-source.png"
    if icon_path.is_file():
        application.setWindowIcon(QIcon(str(icon_path)))
    apply_application_style(application)

    window = MainWindow(APP_VERSION)
    window.show()
    if os.environ.get("SUBTITLE_TRANSLATOR_SMOKE_TEST") == "1":
        QTimer.singleShot(750, application.quit)
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
