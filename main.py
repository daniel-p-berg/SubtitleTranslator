"""SubtitleTranslator macOS application entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

import i18n
import network_tls
import settings
from ui import MainWindow, apply_application_style


APP_VERSION = "0.9.0-beta.15"


def _choose_first_run_language(
    application: QApplication,
) -> str | None:
    """Choose the interface language before constructing first-run screens."""
    dialog = QDialog()
    dialog.setWindowTitle(i18n.tr("Application Interface"))
    dialog.setMinimumWidth(480)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(26, 24, 26, 24)
    layout.setSpacing(16)
    title = QLabel(i18n.tr("Application Interface"))
    title.setObjectName("dialogTitle")
    layout.addWidget(title)

    form = QFormLayout()
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(12)
    language_combo = QComboBox()
    language_combo.setAccessibleName(i18n.tr("Application language"))
    system_code = i18n.system_language_code()
    language_combo.addItem(
        i18n.tr("Use System Language ({language})").format(
            language=i18n.display_name(system_code)
        ),
        "system",
    )
    for language in i18n.interface_languages():
        language_combo.addItem(language.display_name, language.code)
    form.addRow(i18n.tr("Application language"), language_combo)
    layout.addLayout(form)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dialog.accept)
    ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
    if ok_button:
        ok_button.setObjectName("primaryButton")
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return str(language_combo.currentData() or "system")


def main() -> None:
    """Start the Qt application."""
    smoke_test = os.environ.get("SUBTITLE_TRANSLATOR_SMOKE_TEST") == "1"
    if smoke_test:
        network_tls.verified_ssl_context()

    application = QApplication(sys.argv)
    application.setApplicationName("SubtitleTranslator")
    application.setApplicationDisplayName("SubtitleTranslator")
    application.setOrganizationName("SubtitleTranslator")
    application.setApplicationVersion(APP_VERSION)
    application.setQuitOnLastWindowClosed(True)
    settings_store = settings.SettingsStore()
    first_run = (
        not settings.SETTINGS_PATH.exists()
        and not smoke_test
    )
    preferences = settings_store.load()
    i18n.install_translators(
        application,
        preferences.get("interface_language", "system"),
    )

    icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "app-icon-source.png"
    if icon_path.is_file():
        application.setWindowIcon(QIcon(str(icon_path)))
    apply_application_style(application)

    if first_run:
        selected_language = _choose_first_run_language(application)
        if selected_language:
            preferences["interface_language"] = selected_language
            settings_store.save(preferences)
            i18n.install_translators(application, selected_language)

    window = MainWindow(APP_VERSION, first_run=first_run)
    window.show()
    if smoke_test:
        QTimer.singleShot(750, application.quit)
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
