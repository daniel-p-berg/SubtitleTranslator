"""Modern Qt interface for SubtitleTranslator."""

from __future__ import annotations

import os
import subprocess
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QLocale, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import app_paths
import dependencies
import diagnostics as app_diagnostics
import i18n
import languages
import media_launcher
import mpv_config
import open_subtitles
from operation_control import CancellationToken, OperationCancelled
import pipeline
import settings
import translation_cost
import translator

from i18n import tr


BG = "#0d1117"
PANEL = "#141a22"
SURFACE = "#1b222c"
SURFACE_ACTIVE = "#232d38"
BORDER = "#303a47"
TEXT = "#edf2f5"
MUTED = "#98a5af"
ACCENT = "#48d6c7"
ACCENT_DARK = "#183f3e"
WARM = "#f0b45a"
DANGER = "#f17070"
SUCCESS = "#69d49c"

OPENAI_URL = "https://platform.openai.com/api-keys"
OPEN_SUBTITLES_URL = "https://www.opensubtitles.com/en/consumers"
MPV_INSTALL_URL = "https://mpv.io/installation/"
HOMEBREW_INSTALL_URL = "https://docs.brew.sh/Installation"
PRIVACY_URL = "https://github.com/daniel-p-berg/SubtitleTranslator/blob/main/PRIVACY.md"


def _localized_pipeline_stage(stage: str) -> str:
    """Return a concise localized summary while detailed logs stay English."""
    messages = {
        "inspect": tr("Inspecting media and subtitles..."),
        "source": tr("Preparing the reference subtitle..."),
        "target": tr("Preparing the target subtitle..."),
        "search": tr("Searching OpenSubtitles..."),
        "translate": tr("Translating the subtitle..."),
        "clean": tr("Cleaning the subtitle..."),
        "sync": tr("Validating subtitle timing..."),
        "save": tr("Saving the subtitle..."),
        "merge": tr("Creating and verifying the MKV..."),
        "cleanup": tr("Cleaning up files..."),
        "complete": tr("Ready to watch"),
        "warning": tr("Completed with a warning"),
    }
    return messages.get(stage, tr("Working..."))


def _localized_tool_purpose(name: str) -> str:
    purposes = {
        "ffmpeg": tr("Subtitle extraction and media conversion"),
        "ffprobe": tr("Subtitle language and timing inspection"),
        "mkvmerge": tr("Verified MKV subtitle merging"),
        "mpv": tr("Optional playback showing two subtitles"),
    }
    return purposes[name]


def _localized_install_hint(name: str) -> str:
    hints = {
        "ffmpeg": tr("Install with Homebrew: brew install ffmpeg"),
        "ffprobe": tr("Install with Homebrew: brew install ffmpeg"),
        "mkvmerge": tr("Install with Homebrew: brew install mkvtoolnix"),
        "mpv": tr("Install with Homebrew: brew install mpv"),
    }
    return hints[name]


def _localized_prompt_error(message: str) -> str:
    messages = {
        "Prompt cannot be empty.": tr("Prompt cannot be empty."),
        "Prompt must contain {source_name}.": tr(
            "Prompt must contain {source_name}."
        ),
        "Prompt must contain {target_name}.": tr(
            "Prompt must contain {target_name}."
        ),
        "Prompt must instruct the model to preserve SRT timestamps.": tr(
            "Prompt must instruct the model to preserve SRT timestamps."
        ),
    }
    return messages.get(message, message)


def apply_application_style(application: QApplication) -> None:
    """Apply a restrained dark utility theme with native dimensions."""
    application.setStyle("Fusion")
    application.setStyleSheet(
        f"""
        * {{
            font-size: 13px;
            color: {TEXT};
        }}
        QMainWindow, QDialog, QWidget {{
            background: {BG};
        }}
        QLabel, QCheckBox {{
            background: transparent;
        }}
        QTabWidget::pane {{
            border: 0;
            background: {BG};
        }}
        QTabBar::tab {{
            background: transparent;
            color: {MUTED};
            border: 0;
            border-bottom: 2px solid transparent;
            padding: 12px 20px;
            min-width: 80px;
        }}
        QTabBar::tab:selected {{
            color: {TEXT};
            border-bottom-color: {ACCENT};
        }}
        QGroupBox {{
            background: {PANEL};
            border: 1px solid {BORDER};
            border-radius: 6px;
            margin-top: 12px;
            padding: 18px 14px 14px 14px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 5px;
            color: {MUTED};
        }}
        QLineEdit, QComboBox, QListWidget, QTableWidget, QPlainTextEdit {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 5px;
            padding: 7px 9px;
            selection-background-color: {ACCENT_DARK};
        }}
        QLineEdit, QComboBox {{
            min-height: 20px;
        }}
        QLineEdit:focus, QComboBox:focus, QListWidget:focus,
        QTableWidget:focus, QPlainTextEdit:focus {{
            border-color: {ACCENT};
        }}
        QComboBox::drop-down {{
            border: 0;
            width: 24px;
        }}
        QPushButton, QToolButton {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 5px;
            padding: 8px 13px;
            font-weight: 600;
        }}
        QPushButton:hover, QToolButton:hover {{
            background: {SURFACE_ACTIVE};
            border-color: #485462;
        }}
        QPushButton:pressed, QToolButton:pressed {{
            background: #10151b;
        }}
        QPushButton:disabled, QToolButton:disabled {{
            color: #596570;
            background: #12171d;
            border-color: #242c35;
        }}
        QPushButton#primaryButton {{
            background: {ACCENT};
            color: #071514;
            border-color: {ACCENT};
            padding: 11px 18px;
            font-size: 14px;
        }}
        QPushButton#primaryButton:hover {{
            background: #68e3d6;
        }}
        QPushButton#primaryButton:disabled {{
            color: #66727b;
            background: #1c282d;
            border-color: #2a3a40;
        }}
        QPushButton#dangerButton {{
            color: {DANGER};
        }}
        QToolButton#modeButton {{
            border-radius: 0;
            min-width: 92px;
            min-height: 20px;
            color: {TEXT};
        }}
        QToolButton#modeButton:checked {{
            background: {ACCENT_DARK};
            color: {ACCENT};
            border-color: {ACCENT};
        }}
        QProgressBar {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 4px;
            height: 8px;
            text-align: center;
            color: transparent;
        }}
        QProgressBar::chunk {{
            background: {ACCENT};
            border-radius: 3px;
        }}
        QHeaderView::section {{
            background: {PANEL};
            color: {MUTED};
            border: 0;
            border-bottom: 1px solid {BORDER};
            padding: 8px;
            font-weight: 600;
        }}
        QTableWidget {{
            gridline-color: {BORDER};
        }}
        QScrollBar:vertical {{
            background: {BG};
            width: 10px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: #3a4653;
            min-height: 30px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QCheckBox {{
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
        }}
        QCheckBox::indicator:unchecked {{
            background: {SURFACE};
            border: 1px solid #647281;
            border-radius: 3px;
        }}
        QToolTip {{
            background: #252e38;
            color: {TEXT};
            border: 1px solid #465361;
            padding: 5px;
        }}
        """
    )


class DropFrame(QFrame):
    """Media drop target that only accepts local playable files."""

    file_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropFrame")
        self.setStyleSheet(
            f"""
            QFrame#dropFrame {{
                background: {PANEL};
                border: 1px dashed #465463;
                border-radius: 6px;
            }}
            QFrame#dropFrame:hover {{
                border-color: {ACCENT};
                background: #151e25;
            }}
            """
        )
        self.setMinimumHeight(130)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(7)
        self.title = QLabel(tr("Choose a media file"))
        self.title.setStyleSheet("font-size: 17px; font-weight: 650;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel(tr("MKV, MP4, MOV, M4V, AVI, WebM, TS, or M2TS"))
        self.detail.setStyleSheet(f"color: {MUTED};")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        self.choose = QPushButton(tr("Open File"))
        self.choose.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        self.choose.setMinimumWidth(120)
        self.choose.clicked.connect(self._choose_file)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self.choose)
        button_row.addStretch()
        layout.addWidget(self.title)
        layout.addWidget(self.detail)
        layout.addLayout(button_row)

    def set_media(self, path: str) -> None:
        media = Path(path)
        self.title.setText(media.name)
        try:
            size_gb = media.stat().st_size / (1024**3)
            size_text = f"{QLocale().toString(size_gb, 'f', 2)} GB"
        except OSError:
            size_text = tr("Size unavailable")
        self.detail.setText(f"{size_text}  |  {media.parent}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            if path.suffix.lower() in app_paths.VIDEO_EXTENSIONS:
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self.file_selected.emit(urls[0].toLocalFile())
            event.acceptProposedAction()

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        self._choose_file()
        super().mouseDoubleClickEvent(event)

    def _choose_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            tr("Choose Media"),
            str(Path.home() / "Downloads"),
            tr("Media files") + " (*.mkv *.mp4 *.m4v *.mov *.avi *.webm *.ts *.m2ts)",
        )
        if path:
            self.file_selected.emit(path)


class FunctionThread(QThread):
    """Execute a callable without blocking Qt's event loop."""

    completed = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        function: Callable[[], Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.function = function

    def run(self) -> None:
        try:
            self.completed.emit(self.function())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(exc)


class PipelineThread(QThread):
    """Run one subtitle pipeline job and relay structured progress."""

    progress = Signal(str, str, int)
    completed = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    diagnostics_ready = Signal(object)

    def __init__(
        self,
        options: pipeline.PipelineOptions,
        *,
        app_version: str,
    ) -> None:
        super().__init__()
        self.options = options
        self.cancellation_token = CancellationToken()
        self.diagnostics_recorder = app_diagnostics.DiagnosticsRecorder(
            app_version=app_version,
            operation="prepare subtitles",
            media_path=options.video_path,
        )

    def cancel(self) -> None:
        self.cancellation_token.cancel()

    def run(self) -> None:
        try:
            worker = pipeline.SubtitlePipeline(
                lambda stage, message, percent: self.progress.emit(
                    stage,
                    message,
                    percent,
                ),
                cancellation_token=self.cancellation_token,
                diagnostics_recorder=self.diagnostics_recorder,
            )
            self.completed.emit(worker.run(self.options))
        except OperationCancelled:
            self.diagnostics_recorder.record(
                "pipeline",
                "cancelled",
                status="cancelled",
            )
            self.diagnostics_recorder.update_summary(status="cancelled")
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001
            self.diagnostics_recorder.record(
                "pipeline",
                "failed",
                status="error",
                error_type=type(exc).__name__,
                message=str(exc),
            )
            self.diagnostics_recorder.update_summary(
                status="failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self.failed.emit(exc)
        finally:
            self.diagnostics_ready.emit(self.diagnostics_recorder.report())


class CandidateDialog(QDialog):
    """Manual OpenSubtitles result review with editable search terms."""

    candidate_chosen = Signal(object)
    translation_requested = Signal()

    def __init__(
        self,
        parent: QWidget,
        *,
        api_key: str,
        video_path: str,
        target_language: str,
        initial_result: open_subtitles.SubtitleSearchResult | None = None,
        allow_translation: bool = False,
        translation_summary: str = "",
        rejection_reasons: dict[int, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.video_path = video_path
        self.target_language = target_language
        self._candidates: list[open_subtitles.SubtitleCandidate] = []
        self._thread: FunctionThread | None = None
        self._cancellation_token: CancellationToken | None = None
        self.allow_translation = allow_translation
        self.rejection_reasons = dict(rejection_reasons or {})

        target_name = i18n.display_name(target_language)
        self.setWindowTitle(
            tr("Review {language} Results").format(language=target_name)
        )
        self.resize(900, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(
            tr("OpenSubtitles results / {language}").format(
                language=target_name
            )
        )
        title.setStyleSheet("font-size: 18px; font-weight: 650;")
        layout.addWidget(title)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("Movie or episode title"))
        self.search_button = QPushButton(tr("Search"))
        self.search_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.search_button.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        self.cancel_search_button = QToolButton()
        self.cancel_search_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_DialogCancelButton
            )
        )
        self.cancel_search_button.setToolTip(tr("Cancel search"))
        self.cancel_search_button.setEnabled(False)
        self.cancel_search_button.clicked.connect(self._cancel_search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_button)
        search_row.addWidget(self.cancel_search_button)
        layout.addLayout(search_row)
        if not self.api_key:
            self.search_button.setEnabled(False)
            self.query.setEnabled(False)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                tr("Release"),
                tr("Title"),
                tr("Year"),
                tr("Rating"),
                tr("Downloads"),
                tr("Details"),
            ]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda _item: self._use_selected())
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self.status)

        if allow_translation:
            translation_notice = QLabel(
                translation_summary
                + "\n"
                + tr("OpenAI receives subtitle text only when you translate.")
            )
            translation_notice.setWordWrap(True)
            translation_notice.setStyleSheet(f"color: {WARM};")
            layout.addWidget(translation_notice)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.use_button = buttons.addButton(
            tr("Use Selected"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.translate_button = buttons.addButton(
            tr("Translate"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.translate_button.setVisible(allow_translation)
        self.translate_button.clicked.connect(self._translate)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button:
            cancel_button.setText(tr("Cancel"))
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self._use_selected)
        buttons.rejected.connect(self.reject)
        self.table.itemSelectionChanged.connect(
            lambda: self.use_button.setEnabled(bool(self.table.selectedItems()))
        )
        layout.addWidget(buttons)

        if initial_result:
            self.query.setText(initial_result.query)
            self._populate(initial_result)
        else:
            QTimer.singleShot(0, self._search)

    def _search(self) -> None:
        if self._thread and self._thread.isRunning():
            return
        if not self.api_key:
            self.status.setText(
                tr("Add an OpenSubtitles API key in Settings.")
            )
            return
        self.rejection_reasons.clear()
        query = self.query.text().strip() or None
        self.search_button.setEnabled(False)
        self.cancel_search_button.setEnabled(True)
        self.status.setText(tr("Searching..."))
        self._cancellation_token = CancellationToken()
        worker = pipeline.SubtitlePipeline(
            cancellation_token=self._cancellation_token
        )
        self._thread = FunctionThread(
            lambda: worker.search(
                self.api_key,
                self.video_path,
                self.target_language,
                query_override=query,
            ),
            self,
        )
        self._thread.completed.connect(self._populate)
        self._thread.failed.connect(self._search_failed)
        self._thread.finished.connect(self._search_finished)
        self._thread.start()

    def _search_finished(self) -> None:
        thread = self._thread
        self._thread = None
        self._cancellation_token = None
        self.cancel_search_button.setEnabled(False)
        if thread:
            thread.deleteLater()

    def _populate(self, result: open_subtitles.SubtitleSearchResult) -> None:
        self.search_button.setEnabled(bool(self.api_key))
        self.query.setText(result.query)
        self._candidates = list(result.candidates)
        self.table.setRowCount(len(self._candidates))
        automatic_ids = {item.file_id for item in result.automatic_matches}
        for row, candidate in enumerate(self._candidates):
            release = QTableWidgetItem(candidate.release_name or candidate.file_name)
            rejection_reason = self.rejection_reasons.get(candidate.file_id, "")
            if rejection_reason:
                release.setForeground(QColor(DANGER))
                release.setToolTip(rejection_reason)
            elif candidate.file_id in automatic_ids:
                release.setForeground(QColor(ACCENT))
                release.setToolTip(tr("Strong automatic title match"))
            elif candidate.trusted:
                release.setForeground(QColor(WARM))
                release.setToolTip(
                    tr("Trusted uploader; review title and cut")
                )
            self.table.setItem(row, 0, release)
            self.table.setItem(row, 1, QTableWidgetItem(candidate.feature_title))
            self.table.setItem(row, 2, QTableWidgetItem(candidate.feature_year))
            self.table.setItem(row, 3, QTableWidgetItem(f"{candidate.rating:g}"))
            self.table.setItem(
                row,
                4,
                QTableWidgetItem(
                    QLocale().toString(candidate.download_count)
                ),
            )
            details = QTableWidgetItem(rejection_reason)
            details.setToolTip(rejection_reason)
            if rejection_reason:
                details.setForeground(QColor(DANGER))
            self.table.setItem(row, 5, details)
        self.status.setText(
            tr("{count} results").format(count=len(self._candidates))
            + "; "
            + tr("{count} strong title matches").format(
                count=len(result.automatic_matches)
            )
        )
        if not self.api_key:
            self.status.setText(
                self.status.text()
                + "; "
                + tr("Add an OpenSubtitles API key in Settings.")
            )
        if self._candidates:
            self.table.selectRow(0)

    def _search_failed(self, error: Exception) -> None:
        self.search_button.setEnabled(bool(self.api_key))
        if isinstance(error, OperationCancelled):
            self.status.setText(tr("Search cancelled."))
        else:
            self.status.setText(
                tr("Search failed: {error}").format(error=error)
            )

    def _cancel_search(self) -> None:
        if self._cancellation_token:
            self._cancellation_token.cancel()
            self.cancel_search_button.setEnabled(False)
            self.status.setText(tr("Cancelling search..."))

    def reject(self) -> None:
        self._cancel_search()
        super().reject()

    def _use_selected(self) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self._candidates):
            return
        self.candidate_chosen.emit(self._candidates[row])
        self.accept()

    def _translate(self) -> None:
        if not self.allow_translation:
            return
        self.translation_requested.emit()
        self.accept()


class DependencySetupDialog(QDialog):
    """Guided, user-approved Homebrew setup for local media tools."""

    TOOL_NAMES = ("ffmpeg", "ffprobe", "mkvmerge", "mpv")

    def __init__(self, parent: QWidget, *, include_mpv: bool = True) -> None:
        super().__init__(parent)
        self._watching: tuple[str, ...] = ()
        self.setWindowTitle(tr("Media Tools Setup"))
        self.resize(800, 600)
        self.setMinimumSize(680, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title = QLabel(tr("Local media tools"))
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)

        intro = QLabel(
            tr(
                "SubtitleTranslator uses established command-line tools that "
                "run entirely on this Mac."
            )
            + " "
            + tr("Installation is never silent.")
            + " "
            + tr("The exact Homebrew command is shown below.")
            + " "
            + tr("It opens in a visible Terminal.")
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(intro)

        tool_group = QGroupBox(tr("Tool Status"))
        tool_layout = QGridLayout(tool_group)
        tool_layout.setHorizontalSpacing(14)
        tool_layout.setVerticalSpacing(9)
        tool_layout.addWidget(QLabel(tr("Tool")), 0, 0)
        tool_layout.addWidget(QLabel(tr("Purpose")), 0, 1)
        tool_layout.addWidget(QLabel(tr("State")), 0, 2)
        self.tool_states: dict[str, QLabel] = {}
        for row, name in enumerate(self.TOOL_NAMES, start=1):
            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight: 650;")
            purpose_label = QLabel(_localized_tool_purpose(name))
            purpose_label.setStyleSheet(f"color: {MUTED};")
            purpose_label.setWordWrap(True)
            state = QLabel("")
            state.setAlignment(Qt.AlignmentFlag.AlignTrailing)
            self.tool_states[name] = state
            tool_layout.addWidget(name_label, row, 0)
            tool_layout.addWidget(purpose_label, row, 1)
            tool_layout.addWidget(state, row, 2)
        tool_layout.setColumnStretch(1, 1)
        layout.addWidget(tool_group)

        brew_group = QGroupBox("Homebrew")
        brew_layout = QVBoxLayout(brew_group)
        self.brew_state = QLabel("")
        self.brew_state.setWordWrap(True)
        brew_layout.addWidget(self.brew_state)

        self.include_mpv = QCheckBox(tr("Include optional mpv player"))
        self.include_mpv.setChecked(include_mpv)
        self.include_mpv.toggled.connect(self._refresh)
        brew_layout.addWidget(self.include_mpv)

        command_row = QHBoxLayout()
        self.command_edit = QLineEdit()
        self.command_edit.setReadOnly(True)
        self.command_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.command_edit.setStyleSheet(
            'font-family: "SF Mono", Menlo, monospace;'
        )
        self.copy_button = QPushButton(tr("Copy Command"))
        self.copy_button.clicked.connect(self._copy_command)
        command_row.addWidget(self.command_edit, 1)
        command_row.addWidget(self.copy_button)
        brew_layout.addLayout(command_row)

        self.install_note = QLabel("")
        self.install_note.setWordWrap(True)
        self.install_note.setStyleSheet(f"color: {MUTED};")
        brew_layout.addWidget(self.install_note)
        layout.addWidget(brew_group)

        utility_row = QHBoxLayout()
        self.homebrew_button = QPushButton(tr("Homebrew Instructions"))
        self.homebrew_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(HOMEBREW_INSTALL_URL))
        )
        self.check_button = QPushButton(tr("Check Again"))
        self.check_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.check_button.clicked.connect(self._refresh)
        self.install_button = QPushButton(tr("Install Missing Tools"))
        self.install_button.setObjectName("primaryButton")
        self.install_button.clicked.connect(self._install_missing)
        close_button = QPushButton(tr("Done"))
        close_button.clicked.connect(self.accept)
        utility_row.addWidget(self.homebrew_button)
        utility_row.addWidget(self.check_button)
        utility_row.addStretch()
        layout.addLayout(utility_row)
        completion_row = QHBoxLayout()
        completion_row.addStretch()
        completion_row.addWidget(self.install_button)
        completion_row.addWidget(close_button)
        layout.addLayout(completion_row)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1800)
        self._poll_timer.timeout.connect(self._refresh)
        self._refresh()

    def _selected_missing(self) -> tuple[str, ...]:
        return tuple(
            item.name
            for item in dependencies.dependency_status()
            if not item.available
            and (item.required or (item.name == "mpv" and self.include_mpv.isChecked()))
        )

    def _refresh(self) -> None:
        statuses = dependencies.dependency_status()
        status_by_name = {item.name: item for item in statuses}
        for name in self.TOOL_NAMES:
            item = status_by_name[name]
            state = self.tool_states[name]
            if item.available:
                state.setText(tr("Ready"))
                state.setToolTip(item.path or "")
                state.setStyleSheet(f"color: {SUCCESS}; font-weight: 650;")
            else:
                state.setText(
                    tr("Optional") if not item.required else tr("Missing")
                )
                state.setToolTip(_localized_install_hint(name))
                state.setStyleSheet(f"color: {WARM}; font-weight: 650;")

        missing = self._selected_missing()
        brew = dependencies.resolve_homebrew()
        if brew:
            self.brew_state.setText(
                tr("Homebrew detected at {path}").format(path=brew)
            )
            self.brew_state.setStyleSheet(f"color: {SUCCESS};")
            self.homebrew_button.setText(tr("Homebrew Help"))
        elif not missing:
            self.brew_state.setText(
                tr(
                    "Homebrew was not detected, but every selected tool is "
                    "ready."
                )
            )
            self.brew_state.setStyleSheet(f"color: {SUCCESS};")
            self.homebrew_button.setText(tr("Homebrew Help"))
        else:
            self.brew_state.setText(
                tr("Homebrew is not installed.")
                + " "
                + tr(
                    "Open the official instructions and run the signed "
                    "macOS installer."
                )
                + " "
                + tr("Then return to this window.")
            )
            self.brew_state.setStyleSheet(f"color: {WARM};")
            self.homebrew_button.setText(tr("Install Homebrew"))

        formulae = dependencies.homebrew_formulae_for_tools(missing)
        if formulae:
            self.install_note.setStyleSheet(f"color: {MUTED};")
            self.command_edit.setText(
                dependencies.homebrew_install_command(
                    formulae,
                    executable=brew or "brew",
                )
            )
            self.copy_button.setEnabled(True)
            self.install_button.setEnabled(bool(brew))
            self.install_button.setText(
                tr("Install mpv")
                if formulae == ("mpv",)
                else tr("Install Missing Tools")
            )
            if not self._watching:
                self.install_note.setText(
                    tr(
                        "macOS may ask once for permission to open Terminal. "
                        "Finish there, then return; this window checks "
                        "automatically."
                    )
                )
        else:
            self.command_edit.setText(tr("All selected tools are ready"))
            self.copy_button.setEnabled(False)
            self.install_button.setText(tr("Tools Ready"))
            self.install_button.setEnabled(False)
            if not self._watching:
                self.install_note.setStyleSheet(f"color: {MUTED};")
                self.install_note.setText(
                    tr(
                        "Core processing is ready. mpv is optional and can be "
                        "enabled above for dual-subtitle playback."
                    )
                )

        if self._watching:
            remaining = tuple(
                name
                for name in self._watching
                if not status_by_name[name].available
            )
            if remaining:
                self.install_note.setText(
                    tr("Waiting for Terminal to finish:")
                    + " "
                    + ", ".join(remaining)
                )
            else:
                self._watching = ()
                self._poll_timer.stop()
                self.install_note.setText(
                    tr("Installation complete. The tools are ready.")
                )
                self.install_note.setStyleSheet(f"color: {SUCCESS};")

    def _copy_command(self) -> None:
        command = self.command_edit.text()
        if command and command != tr("All selected tools are ready"):
            QApplication.clipboard().setText(command)
            self.install_note.setStyleSheet(f"color: {MUTED};")
            self.install_note.setText(
                tr("Command copied to the clipboard.")
            )

    def _install_missing(self) -> None:
        missing = self._selected_missing()
        formulae = dependencies.homebrew_formulae_for_tools(missing)
        if not formulae:
            self._refresh()
            return
        command = dependencies.homebrew_install_command(formulae)
        answer = QMessageBox.question(
            self,
            tr("Open Terminal"),
            "SubtitleTranslator "
            + tr("will open Terminal with this command:")
            + f"\n\n{command}\n\n"
            + "Homebrew "
            + tr("controls the downloads and installation.")
            + " "
            + tr("Continue?"),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Open,
            QMessageBox.StandardButton.Open,
        )
        if answer != QMessageBox.StandardButton.Open:
            return
        try:
            dependencies.launch_homebrew_install(formulae)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(
                self,
                tr("Could Not Open Terminal"),
                tr("Terminal could not be opened:")
                + "\n\n"
                + str(exc),
            )
            self._refresh()
            return
        self._watching = missing
        self.install_button.setEnabled(False)
        self.install_note.setStyleSheet(f"color: {MUTED};")
        self.install_note.setText(
            tr(
                "Terminal is open. Complete any prompts there; this status "
                "will update automatically."
            )
        )
        self._poll_timer.start()


class MpvSetupDialog(QDialog):
    """Preview, back up, and safely merge dual-subtitle mpv settings."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("mpv Setup"))
        self.resize(820, 640)
        self.setMinimumSize(680, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel(tr("mpv dual subtitles"))
        title.setStyleSheet("font-size: 19px; font-weight: 650;")
        layout.addWidget(title)

        self.state = QLabel("")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)

        install = QLabel(
            tr(
                "Install mpv from <b>Media Tools Setup</b>, or run "
                "<b>brew install mpv</b> in Terminal."
            )
            + " "
            + tr(
                "This assistant preserves unrelated settings and creates a "
                "backup before changing mpv.conf."
            )
        )
        install.setWordWrap(True)
        layout.addWidget(install)

        positions = QGroupBox(tr("Dual Subtitle Layout"))
        positions_layout = QGridLayout(positions)
        self.primary_position = QSpinBox()
        self.primary_position.setRange(0, 150)
        self.primary_position.setValue(88)
        self.primary_position.setSuffix("%")
        self.secondary_position = QSpinBox()
        self.secondary_position.setRange(0, 150)
        self.secondary_position.setValue(12)
        self.secondary_position.setSuffix("%")
        self.show_secondary = QCheckBox(
            tr("Show the secondary subtitle by default")
        )
        self.show_secondary.setChecked(True)
        self.auto_secondary = QCheckBox(
            tr("Automatically select a secondary subtitle")
        )
        self.auto_secondary.setChecked(True)
        positions_layout.addWidget(QLabel(tr("Primary position")), 0, 0)
        positions_layout.addWidget(self.primary_position, 0, 1)
        positions_layout.addWidget(QLabel(tr("Secondary position")), 0, 2)
        positions_layout.addWidget(self.secondary_position, 0, 3)
        positions_layout.addWidget(self.show_secondary, 1, 0, 1, 2)
        positions_layout.addWidget(self.auto_secondary, 1, 2, 1, 2)
        positions_layout.setColumnStretch(1, 1)
        positions_layout.setColumnStretch(3, 1)
        layout.addWidget(positions)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel(tr("Configuration file")))
        self.config_path = QLineEdit(str(mpv_config.DEFAULT_CONFIG_PATH))
        self.config_path.setReadOnly(True)
        self.config_path.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        open_folder = QToolButton()
        open_folder.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        open_folder.setToolTip(tr("Open configuration folder"))
        open_folder.clicked.connect(self._open_config_folder)
        path_row.addWidget(self.config_path, 1)
        path_row.addWidget(open_folder)
        layout.addLayout(path_row)

        self.preview_label = QLabel(tr("Safe merge preview"))
        self.preview_label.setStyleSheet(f"color: {MUTED}; font-weight: 650;")
        layout.addWidget(self.preview_label)
        self.conflict_state = QLabel("")
        self.conflict_state.setWordWrap(True)
        self.conflict_state.setMinimumHeight(34)
        layout.addWidget(self.conflict_state)
        self.config_preview = QPlainTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.config_preview.setMinimumHeight(120)
        self.config_preview.setMaximumHeight(160)
        layout.addWidget(self.config_preview, 1)

        controls = QLabel(
            f"<b>g-s</b> {tr('selects the primary subtitle.')} "
            f"<b>g-S</b> {tr('selects the secondary subtitle.')} "
            f"<b>Alt+v</b> {tr('toggles the secondary subtitle.')}"
        )
        controls.setWordWrap(True)
        layout.addWidget(controls)

        row = QHBoxLayout()
        setup_button = QPushButton(tr("Media Tools Setup"))
        setup_button.clicked.connect(self._open_tool_setup)
        copy_button = QPushButton(tr("Copy Configuration"))
        copy_button.clicked.connect(self._copy_configuration)
        docs_button = QPushButton(tr("mpv Installation"))
        docs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(MPV_INSTALL_URL))
        )
        self.restore_button = QPushButton(tr("Restore Latest Backup"))
        self.restore_button.clicked.connect(self._restore_backup)
        self.apply_button = QPushButton(tr("Apply Safely"))
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self._apply_configuration)
        close_button = QPushButton(tr("Close"))
        close_button.clicked.connect(self.accept)
        row.addWidget(setup_button)
        row.addWidget(copy_button)
        row.addWidget(docs_button)
        row.addStretch()
        layout.addLayout(row)
        action_row = QHBoxLayout()
        action_row.addStretch()
        action_row.addWidget(self.restore_button)
        action_row.addWidget(close_button)
        action_row.addWidget(self.apply_button)
        layout.addLayout(action_row)

        for control in (
            self.primary_position,
            self.secondary_position,
            self.show_secondary,
            self.auto_secondary,
        ):
            if isinstance(control, QSpinBox):
                control.valueChanged.connect(self._refresh_preview)
            else:
                control.toggled.connect(self._refresh_preview)
        self._refresh_preview()

    def _refresh_preview(self, *_args: object) -> None:
        status = dependencies.resolve_tool("mpv")
        config_ready = mpv_config.managed_config_present()
        tool_state = (
            tr("Detected: {path}").format(path=status)
            if status
            else tr("mpv was not detected on this Mac.")
        )
        config_state = (
            tr("Dual-subtitle settings are installed.")
            if config_ready
            else tr("Dual-subtitle settings are not installed yet.")
        )
        self.state.setText(f"{tool_state}  {config_state}")
        self.state.setStyleSheet(
            f"color: {SUCCESS if status and config_ready else WARM};"
        )
        preview = mpv_config.preview_configuration(
            primary_position=self.primary_position.value(),
            secondary_position=self.secondary_position.value(),
            show_secondary=self.show_secondary.isChecked(),
            auto_select_secondary=self.auto_secondary.isChecked(),
        )
        self.config_preview.setPlainText(preview.proposed_text)
        if preview.conflicts:
            self.conflict_state.setText(
                tr(
                    "Existing values for {options} are preserved above the "
                    "managed block; the managed values take precedence."
                ).format(options=", ".join(preview.conflicts))
            )
            self.conflict_state.setStyleSheet(f"color: {WARM};")
        else:
            self.conflict_state.setText(
                tr("No conflicting mpv settings were found.")
            )
            self.conflict_state.setStyleSheet(f"color: {MUTED};")
        self.restore_button.setEnabled(mpv_config.latest_backup() is not None)

    def _open_tool_setup(self) -> None:
        DependencySetupDialog(self, include_mpv=True).exec()
        self._refresh_preview()

    def _copy_configuration(self) -> None:
        QApplication.clipboard().setText(self.config_preview.toPlainText())

    def _open_config_folder(self) -> None:
        path = mpv_config.DEFAULT_CONFIG_PATH.parent
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(  # noqa: S603
            ["/usr/bin/open", str(path)],
            check=False,
        )

    def _apply_configuration(self) -> None:
        try:
            result = mpv_config.apply_configuration(
                primary_position=self.primary_position.value(),
                secondary_position=self.secondary_position.value(),
                show_secondary=self.show_secondary.isChecked(),
                auto_select_secondary=self.auto_secondary.isChecked(),
            )
        except OSError as exc:
            QMessageBox.critical(
                self,
                tr("Could Not Update mpv"),
                tr("The mpv configuration could not be updated: {error}").format(
                    error=exc
                ),
            )
            return
        message = tr("Dual-subtitle settings were added to mpv.conf.")
        if result.backup_path:
            message += "\n\n" + tr("Backup created: {name}").format(
                name=result.backup_path.name
            )
        QMessageBox.information(self, tr("mpv Updated"), message)
        self._refresh_preview()

    def _restore_backup(self) -> None:
        backup = mpv_config.latest_backup()
        if not backup:
            return
        answer = QMessageBox.question(
            self,
            tr("Restore mpv Backup"),
            tr("Restore {name} over the current mpv.conf?").format(
                name=backup.name
            ),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            mpv_config.restore_backup(backup)
        except OSError as exc:
            QMessageBox.critical(
                self,
                tr("Could Not Restore mpv"),
                tr("The mpv backup could not be restored: {error}").format(
                    error=exc
                ),
            )
            return
        QMessageBox.information(
            self,
            tr("mpv Restored"),
            tr("The latest mpv backup was restored."),
        )
        self._refresh_preview()


class SetupChecklistDialog(QDialog):
    """First-run readiness checklist with direct, testable setup actions."""

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.owner = parent
        self._test_worker: FunctionThread | None = None
        self._connection_results: dict[str, tuple[bool, str]] = {}
        self.setWindowTitle(tr("SubtitleTranslator Setup"))
        self.resize(790, 590)
        self.setMinimumSize(680, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        title = QLabel(tr("Ready on this Mac"))
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)
        intro = QLabel(
            tr(
                "Complete only the parts you plan to use. Credentials stay "
                "in macOS Keychain, and setup checks run directly from this Mac."
            )
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(intro)

        checklist = QGroupBox(tr("Readiness Checklist"))
        grid = QGridLayout(checklist)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.addWidget(QLabel(tr("Item")), 0, 0)
        grid.addWidget(QLabel(tr("State")), 0, 1)
        self.states: dict[str, QLabel] = {}

        rows = (
            (
                "tools",
                tr("Media processing tools"),
                tr("Set Up Tools"),
                self._show_tools,
            ),
            (
                "openai",
                "OpenAI",
                tr("Test Connection"),
                self._test_openai_connection,
            ),
            (
                "opensubtitles",
                "OpenSubtitles",
                tr("Test Connection"),
                self._test_opensubtitles_connection,
            ),
            (
                "folder",
                tr("Approved media folder"),
                tr("Choose Folder"),
                self._choose_folder,
            ),
            (
                "mpv",
                tr("mpv dual subtitles"),
                tr("Configure mpv"),
                self._show_mpv,
            ),
            (
                "sample",
                tr("Try the workflow"),
                tr("Choose Media"),
                self._choose_sample,
            ),
        )
        self.actions: dict[str, QPushButton] = {}
        for row, (key, name, button_text, callback) in enumerate(
            rows,
            start=1,
        ):
            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight: 650;")
            state = QLabel("")
            state.setWordWrap(True)
            action = QPushButton(button_text)
            action.clicked.connect(callback)
            self.states[key] = state
            self.actions[key] = action
            grid.addWidget(name_label, row, 0)
            grid.addWidget(state, row, 1)
            grid.addWidget(action, row, 2)
        grid.setColumnStretch(1, 1)
        layout.addWidget(checklist, 1)

        api_note = QLabel(
            tr(
                "OpenAI is needed only for translation. OpenSubtitles is "
                "needed only for subtitle search."
            )
        )
        api_note.setStyleSheet(f"color: {MUTED};")
        api_note.setWordWrap(True)
        layout.addWidget(api_note)

        row = QHBoxLayout()
        self.api_settings_button = QPushButton(tr("API Settings"))
        self.api_settings_button.clicked.connect(self._open_api_settings)
        self.refresh_setup_button = QPushButton(tr("Check Again"))
        self.refresh_setup_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.refresh_setup_button.clicked.connect(self._refresh)
        self.done_button = QPushButton(tr("Done"))
        self.done_button.setObjectName("primaryButton")
        self.done_button.clicked.connect(self.accept)
        row.addWidget(self.api_settings_button)
        row.addWidget(self.refresh_setup_button)
        row.addStretch()
        row.addWidget(self.done_button)
        layout.addLayout(row)
        self._refresh()

    def _set_state(self, key: str, text: str, ready: bool) -> None:
        label = self.states[key]
        label.setText(text)
        label.setStyleSheet(
            f"color: {SUCCESS if ready else WARM}; font-weight: 600;"
        )

    def _refresh(self) -> None:
        self._set_state(
            "tools",
            tr("Ready")
            if dependencies.required_tools_ready()
            else tr("FFmpeg or MKVToolNix is missing"),
            dependencies.required_tools_ready(),
        )
        try:
            openai_ready = self.owner.secret_store.has(
                settings.OPENAI_SECRET
            )
            opensubtitles_ready = self.owner.secret_store.has(
                settings.OPEN_SUBTITLES_SECRET
            )
        except settings.SecretStorageError:
            openai_ready = opensubtitles_ready = False

        for key, configured in (
            ("openai", openai_ready),
            ("opensubtitles", opensubtitles_ready),
        ):
            tested = self._connection_results.get(key)
            if tested:
                self._set_state(key, tested[1], tested[0])
            else:
                self._set_state(
                    key,
                    tr("Configured; test recommended")
                    if configured
                    else tr("Not configured"),
                    configured,
                )
            self.actions[key].setEnabled(configured and not self._test_worker)

        locations = self.owner.preferences.get("media_locations", [])
        self._set_state(
            "folder",
            tr("{count} approved folder(s)").format(count=len(locations))
            if locations
            else tr("No folder selected"),
            bool(locations),
        )
        mpv_ready = bool(dependencies.resolve_tool("mpv"))
        config_ready = mpv_config.managed_config_present()
        self._set_state(
            "mpv",
            (
                tr("Player and dual-subtitle settings ready")
                if mpv_ready and config_ready
                else tr("Optional setup not complete")
            ),
            mpv_ready and config_ready,
        )
        self._set_state(
            "sample",
            (
                tr("Media selected in Prepare")
                if self.owner.video_path
                else tr("Choose any media file when ready")
            ),
            bool(self.owner.video_path),
        )

    def _show_tools(self) -> None:
        DependencySetupDialog(self, include_mpv=True).exec()
        self._refresh()

    def _show_mpv(self) -> None:
        MpvSetupDialog(self).exec()
        self._refresh()

    def _choose_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            tr("Add Media Folder"),
            str(Path.home() / "Downloads"),
        )
        if directory:
            self.owner.preferences = (
                self.owner.settings_store.add_media_location(directory)
            )
            self.owner._load_media_locations()
            self._refresh()

    def _choose_sample(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Choose Media"),
            str(Path.home() / "Downloads"),
            tr("Media files")
            + " (*.mkv *.mp4 *.m4v *.mov *.avi *.webm *.ts *.m2ts)",
        )
        if path:
            self.owner.tabs.setCurrentIndex(0)
            self.owner._select_media(path)
            self.accept()

    def _open_api_settings(self) -> None:
        if self._test_worker and self._test_worker.isRunning():
            return
        self.owner.tabs.setCurrentIndex(2)
        self.accept()

    def _test_openai_connection(self) -> None:
        self._test_connection("openai")

    def _test_opensubtitles_connection(self) -> None:
        self._test_connection("opensubtitles")

    def _test_connection(self, provider: str) -> None:
        if self._test_worker and self._test_worker.isRunning():
            return
        secret_name = (
            settings.OPENAI_SECRET
            if provider == "openai"
            else settings.OPEN_SUBTITLES_SECRET
        )
        try:
            api_key = self.owner.secret_store.get(secret_name)
        except settings.SecretStorageError as exc:
            QMessageBox.critical(
                self,
                tr("Keychain Error"),
                tr("macOS Keychain reported an error: {error}").format(
                    error=exc
                ),
            )
            return

        if not api_key:
            self._connection_results[provider] = (
                False,
                tr("Not configured"),
            )
            self._refresh()
            return

        model = self.owner.model_combo.currentText().strip()

        def run_tests() -> dict[str, tuple[bool, str]]:
            if provider == "openai":
                try:
                    translator.test_api_key(api_key, model)
                    result = (True, tr("OpenAI connection ready"))
                except Exception as exc:  # noqa: BLE001
                    result = (
                        False,
                        tr("Connection failed: {error}").format(error=exc),
                    )
            else:
                try:
                    open_subtitles.test_api_key(api_key)
                    result = (True, tr("OpenSubtitles connection ready"))
                except Exception as exc:  # noqa: BLE001
                    result = (
                        False,
                        tr("Connection failed: {error}").format(error=exc),
                    )
            return {provider: result}

        for action in self.actions.values():
            action.setEnabled(False)
        self.api_settings_button.setEnabled(False)
        self.refresh_setup_button.setEnabled(False)
        self.done_button.setEnabled(False)
        self.states[provider].setText(tr("Testing..."))
        self._test_worker = FunctionThread(run_tests, self)
        self._test_worker.completed.connect(self._connections_ready)
        self._test_worker.failed.connect(self._connections_failed)
        self._test_worker.finished.connect(self._connection_worker_finished)
        self._test_worker.start()

    def _connections_ready(
        self,
        results: dict[str, tuple[bool, str]],
    ) -> None:
        self._connection_results.update(results)
        self._refresh()

    def _connections_failed(self, error: Exception) -> None:
        QMessageBox.warning(
            self,
            tr("Connection Test Failed"),
            tr("Connection failed: {error}").format(error=error),
        )

    def _connection_worker_finished(self) -> None:
        worker = self._test_worker
        self._test_worker = None
        if worker:
            worker.deleteLater()
        for action in self.actions.values():
            action.setEnabled(True)
        self.api_settings_button.setEnabled(True)
        self.refresh_setup_button.setEnabled(True)
        self.done_button.setEnabled(True)
        self._refresh()

    def reject(self) -> None:
        if self._test_worker and self._test_worker.isRunning():
            QApplication.alert(self, 1200)
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._test_worker and self._test_worker.isRunning():
            QApplication.alert(self, 1200)
            event.ignore()
            return
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(
        self,
        version: str,
        *,
        first_run: bool | None = None,
    ) -> None:
        super().__init__()
        self.version = version
        self.settings_store = settings.SettingsStore()
        self.secret_store = settings.SecretStore()
        self.preferences = self.settings_store.load()
        self.video_path = ""
        self.selected_subtitle_path = ""
        self.selected_candidate: open_subtitles.SubtitleCandidate | None = None
        self.last_result: pipeline.PipelineResult | None = None
        self.last_diagnostics: dict[str, Any] = {}
        self._media_duration_seconds = 0.0
        self._background_workers: list[QThread] = []
        self._inspection_worker: FunctionThread | None = None
        self._pipeline_worker: PipelineThread | None = None
        self._recent_worker: FunctionThread | None = None
        self._inspection_generation = 0
        self._candidate_dialog: CandidateDialog | None = None
        detected_first_run = (
            not settings.SETTINGS_PATH.exists()
            and os.environ.get("SUBTITLE_TRANSLATOR_SMOKE_TEST") != "1"
        )
        self._first_run = (
            detected_first_run if first_run is None else first_run
        )

        settings.ensure_private_directories(
            self.preferences["workspace_directory"]
        )
        with suppress(OSError, settings.SecretStorageError):
            settings.reconcile_legacy_credentials(self.secret_store)

        self.setWindowTitle("SubtitleTranslator")
        self.resize(980, 760)
        self.setMinimumSize(850, 680)
        self._build_ui()
        self._load_preferences_into_ui()
        if self._first_run:
            QTimer.singleShot(300, self._show_first_run)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(22, 14, 22, 18)
        root_layout.setSpacing(8)

        header = QHBoxLayout()
        brand = QLabel("SubtitleTranslator")
        brand.setStyleSheet("font-size: 21px; font-weight: 700;")
        version = QLabel(self.version)
        version.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        privacy = QPushButton(tr("Privacy"))
        privacy.setToolTip(
            tr("View the local-data and network privacy model")
        )
        privacy.clicked.connect(self._show_privacy)
        tools_button = QPushButton(tr("Media Tools"))
        tools_button.setToolTip(
            tr("Check or install local processing tools")
        )
        tools_button.clicked.connect(self._show_dependency_setup)
        setup_button = QPushButton(tr("Setup"))
        setup_button.setToolTip(tr("Open the readiness checklist"))
        setup_button.clicked.connect(self._show_setup_checklist)
        header.addWidget(brand)
        header.addWidget(version)
        header.addStretch()
        header.addWidget(setup_button)
        header.addWidget(tools_button)
        header.addWidget(privacy)
        root_layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_prepare_tab(), tr("Prepare"))
        self.tabs.addTab(self._build_recent_tab(), tr("Recent"))
        self.tabs.addTab(self._build_settings_tab(), tr("Settings"))
        self.tabs.currentChanged.connect(self._tab_changed)
        root_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def _build_prepare_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        page.setMinimumHeight(640)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        self.drop_frame = DropFrame()
        self.drop_frame.file_selected.connect(self._select_media)
        layout.addWidget(self.drop_frame)

        self.inspect_label = QLabel(tr("No media selected"))
        self.inspect_label.setStyleSheet(f"color: {MUTED};")
        self.inspect_label.setWordWrap(True)
        layout.addWidget(self.inspect_label)

        controls = QGroupBox(tr("Languages and Method"))
        controls.setMinimumHeight(166)
        control_grid = QGridLayout(controls)
        control_grid.setHorizontalSpacing(14)
        control_grid.setVerticalSpacing(11)
        self.source_combo = QComboBox()
        self.source_combo.addItem(tr("Auto-detect"), "auto")
        self.target_combo = QComboBox()
        for language in languages.all_languages():
            display = i18n.display_name(language.code)
            self.source_combo.addItem(display, language.code)
            self.target_combo.addItem(display, language.code)
        self.target_combo.currentIndexChanged.connect(
            self._update_cost_estimate
        )
        control_grid.addWidget(QLabel(tr("Source")), 0, 0)
        control_grid.addWidget(self.source_combo, 1, 0)
        control_grid.addWidget(QLabel(tr("Target")), 0, 1)
        control_grid.addWidget(self.target_combo, 1, 1)

        mode_label = QLabel(tr("Method"))
        control_grid.addWidget(mode_label, 2, 0)
        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QToolButton] = {}
        mode_labels = {
            "automatic": tr("Automatic"),
            "find": tr("Find"),
            "translate": tr("Translate"),
        }
        for index, code in enumerate(("automatic", "find", "translate")):
            button = QToolButton()
            button.setText(mode_labels[code])
            button.setCheckable(True)
            button.setObjectName("modeButton")
            button.setMinimumHeight(34)
            if index == 0:
                button.setChecked(True)
            self.mode_group.addButton(button)
            self.mode_buttons[code] = button
            button.toggled.connect(self._update_cost_estimate)
            mode_row.addWidget(button)
        mode_row.addStretch()
        review_button = QPushButton(tr("Review Search Results"))
        review_button.setMinimumHeight(34)
        review_button.clicked.connect(self._open_candidate_review)
        mode_row.addWidget(review_button)
        control_grid.addLayout(mode_row, 3, 0, 1, 2)
        control_grid.setRowMinimumHeight(3, 42)

        sidecar_container = QFrame()
        sidecar_row = QHBoxLayout(sidecar_container)
        sidecar_row.setContentsMargins(4, 0, 4, 0)
        self.sidecar_label = QLabel(tr("Target subtitle: automatic"))
        self.sidecar_label.setStyleSheet(f"color: {MUTED};")
        choose_sidecar = QPushButton(tr("Choose Subtitle"))
        choose_sidecar.setMinimumHeight(34)
        choose_sidecar.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        )
        choose_sidecar.clicked.connect(self._choose_sidecar)
        clear_sidecar = QToolButton()
        clear_sidecar.setMinimumSize(34, 34)
        clear_sidecar.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        clear_sidecar.setToolTip(tr("Clear selected subtitle"))
        clear_sidecar.clicked.connect(self._clear_sidecar)
        sidecar_row.addWidget(self.sidecar_label, 1)
        sidecar_row.addWidget(choose_sidecar)
        sidecar_row.addWidget(clear_sidecar)
        layout.addWidget(controls)
        layout.addWidget(sidecar_container)

        output_group = QGroupBox(tr("Output"))
        output_group.setMinimumHeight(104)
        output_layout = QGridLayout(output_group)
        self.merge_checkbox = QCheckBox(tr("Create merged MKV"))
        self.merge_checkbox.setChecked(True)
        self.keep_srt_checkbox = QCheckBox(tr("Keep final SRT"))
        self.keep_srt_checkbox.setChecked(True)
        self.clean_checkbox = QCheckBox(
            tr("Clean working files after success")
        )
        self.delete_original_checkbox = QCheckBox(
            tr("Move original to Trash after verified merge")
        )
        self.delete_original_checkbox.setStyleSheet(f"color: {DANGER};")
        self.merge_checkbox.toggled.connect(
            self.delete_original_checkbox.setEnabled
        )
        output_layout.addWidget(self.merge_checkbox, 0, 0)
        output_layout.addWidget(self.keep_srt_checkbox, 0, 1)
        output_layout.addWidget(self.clean_checkbox, 1, 0)
        output_layout.addWidget(self.delete_original_checkbox, 1, 1)
        layout.addWidget(output_group)

        action_row = QHBoxLayout()
        self.cost_label = QLabel("")
        self.cost_label.setWordWrap(True)
        self.cost_label.setStyleSheet(f"color: {MUTED};")
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_DialogCancelButton
            )
        )
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel_pipeline)
        self.primary_button = QPushButton(tr("Prepare Subtitles"))
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setEnabled(False)
        self.primary_button.clicked.connect(self._start_pipeline)
        action_row.addWidget(self.cost_label, 1)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.primary_button)
        layout.addLayout(action_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.details_toggle = QToolButton()
        self.details_toggle.setText(tr("Details"))
        self.details_toggle.setCheckable(True)
        self.details_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.details_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.details_toggle.toggled.connect(self._toggle_details)
        details_row = QHBoxLayout()
        self.export_diagnostics_button = QPushButton(
            tr("Export Diagnostics")
        )
        self.export_diagnostics_button.setToolTip(
            tr("Save a redacted local report")
        )
        self.export_diagnostics_button.setEnabled(False)
        self.export_diagnostics_button.clicked.connect(
            self._export_diagnostics
        )
        details_row.addWidget(self.details_toggle)
        details_row.addStretch()
        details_row.addWidget(self.export_diagnostics_button)
        layout.addLayout(details_row)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.details.setMaximumBlockCount(500)
        self.details.setVisible(False)
        self.details.setMinimumHeight(110)
        layout.addWidget(self.details)

        self.result_frame = QFrame()
        result_layout = QHBoxLayout(self.result_frame)
        result_layout.setContentsMargins(0, 4, 0, 0)
        self.result_label = QLabel("")
        self.result_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.result_label.setWordWrap(True)
        self.play_button = QPushButton(tr("Open in mpv"))
        self.play_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.play_button.clicked.connect(self._play_result)
        self.reveal_button = QPushButton(tr("Show in Finder"))
        self.reveal_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.reveal_button.clicked.connect(self._reveal_result)
        result_layout.addWidget(self.result_label, 1)
        result_layout.addWidget(self.reveal_button)
        result_layout.addWidget(self.play_button)
        self.result_frame.setVisible(False)
        layout.addWidget(self.result_frame)
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    def _build_recent_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel(tr("Recent media"))
        title.setStyleSheet("font-size: 18px; font-weight: 650;")
        refresh = QPushButton(tr("Refresh"))
        refresh.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        refresh.clicked.connect(self._refresh_recent)
        add_folder = QPushButton(tr("Add Media Folder"))
        add_folder.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        add_folder.clicked.connect(self._add_media_location)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(add_folder)
        top.addWidget(refresh)
        layout.addLayout(top)

        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(lambda _item: self._play_recent())
        layout.addWidget(self.recent_list, 1)

        buttons = QHBoxLayout()
        load = QPushButton(tr("Load in Prepare"))
        load.clicked.connect(self._load_recent)
        play = QPushButton(tr("Open in mpv"))
        play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        play.clicked.connect(self._play_recent)
        buttons.addStretch()
        buttons.addWidget(load)
        buttons.addWidget(play)
        layout.addLayout(buttons)
        return page

    def _build_settings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 12, 8, 8)
        layout.setSpacing(12)

        interface_group = QGroupBox(tr("Application Interface"))
        interface_layout = QGridLayout(interface_group)
        self.interface_combo = QComboBox()
        self.interface_combo.addItem(
            tr("Use System Language ({language})").format(
                language=i18n.display_name(i18n.system_language_code())
            ),
            "system",
        )
        for language in i18n.interface_languages():
            self.interface_combo.addItem(
                language.display_name,
                language.code,
            )
        interface_layout.addWidget(QLabel(tr("Application language")), 0, 0)
        interface_layout.addWidget(self.interface_combo, 0, 1)
        restart_note = QLabel(tr("Language changes apply after restarting the app."))
        restart_note.setStyleSheet(f"color: {MUTED};")
        restart_note.setWordWrap(True)
        interface_layout.addWidget(restart_note, 1, 1)
        interface_layout.setColumnStretch(1, 1)
        layout.addWidget(interface_group)

        api_group = QGroupBox(tr("API Connections"))
        api_layout = QGridLayout(api_group)
        self.openai_key = QLineEdit()
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setPlaceholderText(tr("Stored in macOS Keychain"))
        self.openai_key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.os_key = QLineEdit()
        self.os_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.os_key.setPlaceholderText(tr("Stored in macOS Keychain"))
        self.os_key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.openai_state = QLabel("")
        self.os_state = QLabel("")
        test_openai = QPushButton(tr("Test"))
        test_openai.clicked.connect(self._test_openai)
        test_os = QPushButton(tr("Test"))
        test_os.clicked.connect(self._test_opensubtitles)
        openai_link = QToolButton()
        openai_link.setText(tr("Get API Key"))
        openai_link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(OPENAI_URL))
        )
        os_link = QToolButton()
        os_link.setText(tr("Get API Key"))
        os_link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(OPEN_SUBTITLES_URL))
        )
        api_layout.addWidget(QLabel("OpenAI"), 0, 0)
        api_layout.addWidget(self.openai_key, 0, 1)
        api_layout.addWidget(test_openai, 0, 2)
        api_layout.addWidget(openai_link, 0, 3)
        api_layout.addWidget(self.openai_state, 1, 1, 1, 3)
        api_layout.addWidget(QLabel("OpenSubtitles"), 2, 0)
        api_layout.addWidget(self.os_key, 2, 1)
        api_layout.addWidget(test_os, 2, 2)
        api_layout.addWidget(os_link, 2, 3)
        api_layout.addWidget(self.os_state, 3, 1, 1, 3)
        save_keys = QPushButton(tr("Save API Keys to Keychain"))
        save_keys.clicked.connect(self._save_keys)
        forget_keys = QPushButton(tr("Remove API Keys"))
        forget_keys.setObjectName("dangerButton")
        forget_keys.clicked.connect(self._forget_keys)
        key_buttons = QHBoxLayout()
        key_buttons.addStretch()
        key_buttons.addWidget(forget_keys)
        key_buttons.addWidget(save_keys)
        api_layout.addLayout(key_buttons, 4, 0, 1, 4)
        layout.addWidget(api_group)

        files_group = QGroupBox(tr("File Locations"))
        files_layout = QGridLayout(files_group)
        self.media_locations = QListWidget()
        self.media_locations.setMaximumHeight(105)
        media_buttons = QVBoxLayout()
        add_media = QToolButton()
        add_media.setText(tr("Add"))
        add_media.clicked.connect(self._add_media_location)
        remove_media = QToolButton()
        remove_media.setText(tr("Remove"))
        remove_media.clicked.connect(self._remove_media_location)
        media_buttons.addWidget(add_media)
        media_buttons.addWidget(remove_media)
        media_buttons.addStretch()
        files_layout.addWidget(QLabel(tr("Folders containing media")), 0, 0)
        files_layout.addWidget(self.media_locations, 1, 0, 1, 3)
        files_layout.addLayout(media_buttons, 1, 3)

        self.workspace_edit = QLineEdit()
        self.workspace_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        workspace_browse = QToolButton()
        workspace_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        workspace_browse.setToolTip(tr("Choose working folder"))
        workspace_browse.clicked.connect(self._choose_workspace)
        workspace_open = QToolButton()
        workspace_open.setText(tr("Open"))
        workspace_open.clicked.connect(self._open_workspace)
        files_layout.addWidget(QLabel(tr("App working folder")), 2, 0)
        files_layout.addWidget(self.workspace_edit, 2, 1)
        files_layout.addWidget(workspace_browse, 2, 2)
        files_layout.addWidget(workspace_open, 2, 3)

        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem(
            tr("Beside original media"),
            "alongside",
        )
        self.output_mode_combo.addItem(tr("Custom folder"), "custom")
        self.output_mode_combo.currentIndexChanged.connect(
            self._output_mode_changed
        )
        self.custom_output_edit = QLineEdit()
        self.custom_output_edit.setLayoutDirection(
            Qt.LayoutDirection.LeftToRight
        )
        output_browse = QToolButton()
        output_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        output_browse.setToolTip(tr("Choose output folder"))
        output_browse.clicked.connect(self._choose_output)
        files_layout.addWidget(QLabel(tr("Output location")), 3, 0)
        files_layout.addWidget(self.output_mode_combo, 3, 1)
        files_layout.addWidget(self.custom_output_edit, 4, 1)
        files_layout.addWidget(output_browse, 4, 2)
        layout.addWidget(files_group)

        translation_group = QGroupBox(tr("Subtitle Translation"))
        translation_layout = QGridLayout(translation_group)
        self._setting_translation_controls = False
        preset_row = QHBoxLayout()
        self.quality_group = QButtonGroup(self)
        self.quality_group.setExclusive(True)
        self.quality_buttons: dict[str, QToolButton] = {}
        for code, label in (
            ("economy", tr("Economy")),
            ("balanced", tr("Balanced")),
            ("best", tr("Best")),
        ):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setObjectName("modeButton")
            button.setMinimumHeight(34)
            button.clicked.connect(
                lambda _checked=False, preset=code: self._apply_quality_preset(
                    preset
                )
            )
            self.quality_group.addButton(button)
            self.quality_buttons[code] = button
            preset_row.addWidget(button)
        self.quality_state = QLabel("")
        self.quality_state.setStyleSheet(f"color: {MUTED};")
        preset_row.addWidget(self.quality_state)
        preset_row.addStretch()
        translation_layout.addWidget(QLabel(tr("Quality preset")), 0, 0)
        translation_layout.addLayout(preset_row, 0, 1, 1, 3)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.model_combo.addItems(
            ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
        )
        self.reasoning_combo = QComboBox()
        for value, label in (
            ("none", tr("None")),
            ("low", tr("Low")),
            ("medium", tr("Medium")),
            ("high", tr("High")),
            ("xhigh", tr("Extra High")),
            ("max", tr("Maximum")),
        ):
            self.reasoning_combo.addItem(label, value)
        self.model_combo.currentTextChanged.connect(
            self._advanced_translation_changed
        )
        self.reasoning_combo.currentIndexChanged.connect(
            self._advanced_translation_changed
        )
        translation_layout.addWidget(QLabel(tr("OpenAI model")), 1, 0)
        translation_layout.addWidget(self.model_combo, 1, 1)
        translation_layout.addWidget(QLabel(tr("Reasoning")), 1, 2)
        translation_layout.addWidget(self.reasoning_combo, 1, 3)

        self.settings_cost_label = QLabel("")
        self.settings_cost_label.setWordWrap(True)
        self.settings_cost_label.setStyleSheet(f"color: {MUTED};")
        translation_layout.addWidget(
            self.settings_cost_label,
            2,
            1,
            1,
            3,
        )

        self.prompt_language_combo = QComboBox()
        for language in languages.all_languages():
            self.prompt_language_combo.addItem(
                i18n.display_name(language.code),
                language.code,
            )
        self.prompt_language_combo.currentIndexChanged.connect(
            self._load_prompt_editor
        )
        translation_layout.addWidget(QLabel(tr("Prompt profile")), 3, 0)
        translation_layout.addWidget(self.prompt_language_combo, 3, 1, 1, 3)
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.prompt_editor.setMinimumHeight(210)
        translation_layout.addWidget(self.prompt_editor, 4, 0, 1, 4)
        prompt_buttons = QHBoxLayout()
        reset_prompt = QPushButton(tr("Reset Default"))
        reset_prompt.clicked.connect(self._reset_prompt)
        save_prompt = QPushButton(tr("Save Prompt"))
        save_prompt.clicked.connect(self._save_prompt)
        prompt_buttons.addStretch()
        prompt_buttons.addWidget(reset_prompt)
        prompt_buttons.addWidget(save_prompt)
        translation_layout.addLayout(prompt_buttons, 5, 0, 1, 4)
        layout.addWidget(translation_group)

        playback_group = QGroupBox(tr("Video Playback"))
        playback_layout = QGridLayout(playback_group)
        self.mpv_path_edit = QLineEdit()
        self.mpv_path_edit.setPlaceholderText(tr("Auto-detect mpv"))
        self.mpv_path_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        mpv_browse = QToolButton()
        mpv_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        mpv_browse.setToolTip(tr("Choose mpv executable"))
        mpv_browse.clicked.connect(self._choose_mpv)
        setup = QPushButton(tr("Dual Subtitle Setup"))
        setup.clicked.connect(lambda: MpvSetupDialog(self).exec())
        playback_layout.addWidget(QLabel(tr("mpv executable")), 0, 0)
        playback_layout.addWidget(self.mpv_path_edit, 0, 1)
        playback_layout.addWidget(mpv_browse, 0, 2)
        playback_layout.addWidget(setup, 1, 1, 1, 2)
        layout.addWidget(playback_group)

        dependency_group = QGroupBox(tr("Media Tools"))
        dependency_layout = QVBoxLayout(dependency_group)
        self.dependency_label = QLabel("")
        self.dependency_label.setWordWrap(True)
        dependency_layout.addWidget(self.dependency_label)
        dependency_buttons = QHBoxLayout()
        setup_dependencies = QPushButton(tr("Set Up Tools"))
        setup_dependencies.clicked.connect(self._show_dependency_setup)
        check_dependencies = QPushButton(tr("Check Again"))
        check_dependencies.clicked.connect(self._update_dependency_status)
        dependency_buttons.addStretch()
        dependency_buttons.addWidget(check_dependencies)
        dependency_buttons.addWidget(setup_dependencies)
        dependency_layout.addLayout(dependency_buttons)
        layout.addWidget(dependency_group)

        save_settings = QPushButton(tr("Save Settings"))
        save_settings.setObjectName("primaryButton")
        save_settings.clicked.connect(self._save_preferences)
        layout.addWidget(
            save_settings,
            alignment=Qt.AlignmentFlag.AlignTrailing,
        )
        layout.addStretch()

        scroll.setWidget(content)
        return scroll

    def _load_preferences_into_ui(self) -> None:
        _set_combo_data(self.target_combo, self.preferences["target_language"])
        _set_combo_data(self.source_combo, self.preferences["source_language"])
        _set_combo_data(
            self.interface_combo,
            self.preferences.get("interface_language", "system"),
        )
        self.clean_checkbox.setChecked(self.preferences["cleanup_intermediates"])
        self.workspace_edit.setText(self.preferences["workspace_directory"])
        _set_combo_data(self.output_mode_combo, self.preferences["output_mode"])
        self.custom_output_edit.setText(
            self.preferences["custom_output_directory"]
        )
        self._setting_translation_controls = True
        self.model_combo.setCurrentText(self.preferences["translation_model"])
        _set_combo_data(
            self.reasoning_combo,
            self.preferences["reasoning_effort"],
        )
        self._setting_translation_controls = False
        self._sync_quality_buttons()
        self.mpv_path_edit.setText(self.preferences["mpv_path"])
        self.media_locations.clear()
        self.media_locations.addItems(self.preferences["media_locations"])
        self._load_prompt_editor()
        self._output_mode_changed()
        self._update_key_states()
        self._update_dependency_status()
        self._update_cost_estimate()

    def _start_background_worker(self, worker: QThread) -> None:
        """Retain every active Qt worker until its thread has finished."""
        self._background_workers.append(worker)
        worker.finished.connect(
            lambda active=worker: self._background_worker_finished(active)
        )
        worker.start()

    def _background_worker_finished(self, worker: QThread) -> None:
        if worker in self._background_workers:
            self._background_workers.remove(worker)
        if worker is self._inspection_worker:
            self._inspection_worker = None
        if worker is self._pipeline_worker:
            self._pipeline_worker = None
        if worker is self._recent_worker:
            self._recent_worker = None
        worker.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Keep Qt workers alive until their current operation has finished."""
        workers = {*self._background_workers, *self.findChildren(QThread)}
        if any(worker.isRunning() for worker in workers):
            self.status_label.setText(tr("Working..."))
            self._append_detail(
                "Quit requested while a background task is still running."
            )
            QApplication.alert(self, 1500)
            event.ignore()
            return
        super().closeEvent(event)

    def _select_media(self, path: str) -> None:
        if self._pipeline_worker and self._pipeline_worker.isRunning():
            return
        media = Path(path).expanduser().resolve()
        if not media.is_file() or media.suffix.lower() not in app_paths.VIDEO_EXTENSIONS:
            QMessageBox.warning(
                self,
                tr("Unsupported File"),
                tr("Choose a supported media file."),
            )
            return
        self.video_path = str(media)
        self._media_duration_seconds = 0.0
        self.selected_subtitle_path = ""
        self.selected_candidate = None
        self.sidecar_label.setText(tr("Target subtitle: automatic"))
        self.drop_frame.set_media(self.video_path)
        self.primary_button.setEnabled(False)
        self.result_frame.setVisible(False)
        self.inspect_label.setText(tr("Inspecting subtitle tracks..."))
        self._update_cost_estimate()
        self.preferences = self.settings_store.remember_media_file(media)

        target = self.target_combo.currentData()
        roots = list(self.preferences["media_locations"])
        self._inspection_generation += 1
        generation = self._inspection_generation
        selected_path = self.video_path
        worker = FunctionThread(
            lambda: pipeline.SubtitlePipeline().inspect(
                selected_path,
                target_language=target,
                media_roots=roots,
            ),
            self,
        )
        self._inspection_worker = worker
        worker.completed.connect(
            lambda inspection: self._inspection_complete(
                generation,
                selected_path,
                inspection,
            )
        )
        worker.failed.connect(
            lambda error: self._inspection_failed(
                generation,
                selected_path,
                error,
            )
        )
        self._start_background_worker(worker)

    def _inspection_complete(
        self,
        generation: int,
        selected_path: str,
        inspection: pipeline.MediaInspection,
    ) -> None:
        if (
            generation != self._inspection_generation
            or selected_path != self.video_path
        ):
            return
        self.primary_button.setEnabled(True)
        self._media_duration_seconds = inspection.duration_seconds
        text_count = sum(1 for track in inspection.tracks if track.text_based)
        image_count = len(inspection.tracks) - text_count
        if inspection.suggested_source_language in {"auto", "und"}:
            source = tr("not identified")
        else:
            source = i18n.display_name(
                inspection.suggested_source_language
            )
        target_state = (
            tr("target found")
            if inspection.target_available
            else tr("target not found")
        )
        self.inspect_label.setText(
            " | ".join(
                (
                    tr("{count} text subtitle streams").format(
                        count=text_count
                    ),
                    tr("{count} image subtitle streams").format(
                        count=image_count
                    ),
                    tr("{count} sidecar files").format(
                        count=len(inspection.sidecars)
                    ),
                    tr("source: {source}").format(source=source),
                    target_state,
                )
            )
        )
        if (
            self.source_combo.currentData() == "auto"
            and inspection.suggested_source_language != "auto"
        ):
            _set_combo_data(
                self.source_combo,
                inspection.suggested_source_language,
            )
        self._update_cost_estimate()

    def _inspection_failed(
        self,
        generation: int,
        selected_path: str,
        error: Exception,
    ) -> None:
        if (
            generation != self._inspection_generation
            or selected_path != self.video_path
        ):
            return
        self.primary_button.setEnabled(True)
        self.inspect_label.setText(
            tr("Subtitle inspection unavailable: {error}").format(error=error)
        )

    def _choose_sidecar(self) -> None:
        initial = str(Path(self.video_path).parent) if self.video_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Choose Target Subtitle"),
            initial,
            tr("Subtitle files") + " (*.srt *.ass *.ssa *.vtt)",
        )
        if path:
            self.selected_subtitle_path = path
            self.selected_candidate = None
            self.sidecar_label.setText(
                tr("Target subtitle: {name}").format(name=Path(path).name)
            )
            self._update_cost_estimate()

    def _clear_sidecar(self) -> None:
        self.selected_subtitle_path = ""
        self.selected_candidate = None
        self.sidecar_label.setText(tr("Target subtitle: automatic"))
        self._update_cost_estimate()

    def _start_pipeline(self) -> None:
        self._start_pipeline_for_strategy()

    def _start_pipeline_for_strategy(
        self,
        strategy_override: pipeline.Strategy | None = None,
    ) -> None:
        if (
            not self.video_path
            or (
                self._inspection_worker
                and self._inspection_worker.isRunning()
            )
            or (
                self._pipeline_worker
                and self._pipeline_worker.isRunning()
            )
        ):
            return
        if not dependencies.required_tools_ready():
            self._show_dependency_setup()
            if not dependencies.required_tools_ready():
                return
        if not self.merge_checkbox.isChecked() and not self.keep_srt_checkbox.isChecked():
            QMessageBox.warning(
                self,
                tr("No Output Selected"),
                tr("Select a merged MKV, a final SRT, or both."),
            )
            return
        if self.delete_original_checkbox.isChecked():
            answer = QMessageBox.warning(
                self,
                tr("Move Original to Trash"),
                tr(
                    "After the merged MKV passes verification, the original "
                    "media will be moved to Trash. Continue?"
                ),
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._save_preferences(silent=True)
        method = strategy_override or next(
            code for code, button in self.mode_buttons.items() if button.isChecked()
        )
        try:
            openai_key = (
                self.secret_store.get(settings.OPENAI_SECRET)
                if method in {"automatic", "translate"}
                else ""
            )
            os_key = (
                self.secret_store.get(settings.OPEN_SUBTITLES_SECRET)
                if method in {"automatic", "find"}
                else ""
            )
        except settings.SecretStorageError as exc:
            QMessageBox.critical(
                self,
                tr("Keychain Error"),
                tr("macOS Keychain reported an error: {error}").format(
                    error=exc
                ),
            )
            return

        target_code = self.target_combo.currentData()
        prompt = self.preferences["prompt_overrides"].get(target_code, "")
        options = pipeline.PipelineOptions(
            video_path=self.video_path,
            target_language=target_code,
            source_language=self.source_combo.currentData(),
            strategy=method,
            selected_subtitle_path=self.selected_subtitle_path,
            selected_candidate=self.selected_candidate,
            media_roots=list(self.preferences["media_locations"]),
            workspace_directory=self.preferences["workspace_directory"],
            output_mode=self.preferences["output_mode"],
            custom_output_directory=self.preferences["custom_output_directory"],
            save_final_subtitle=self.keep_srt_checkbox.isChecked(),
            create_merged_video=self.merge_checkbox.isChecked(),
            cleanup_intermediates=self.clean_checkbox.isChecked(),
            delete_original_after_merge=self.delete_original_checkbox.isChecked(),
            openai_api_key=openai_key,
            opensubtitles_api_key=os_key,
            translation_model=self.preferences["translation_model"],
            reasoning_effort=self.preferences["reasoning_effort"],
            prompt_template=prompt,
        )
        self._set_busy(True)
        self.details.clear()
        self.last_diagnostics = {}
        self.export_diagnostics_button.setEnabled(False)
        self._append_detail("Job started")
        worker = PipelineThread(options, app_version=self.version)
        self._pipeline_worker = worker
        worker.progress.connect(self._pipeline_progress)
        worker.completed.connect(self._pipeline_complete)
        worker.failed.connect(self._pipeline_failed)
        worker.cancelled.connect(self._pipeline_cancelled)
        worker.diagnostics_ready.connect(self._pipeline_diagnostics_ready)
        self._start_background_worker(worker)

    def _pipeline_progress(self, stage: str, message: str, percent: int) -> None:
        if percent:
            self.progress_bar.setValue(percent)
        self.status_label.setText(_localized_pipeline_stage(stage))
        self._append_detail(f"{stage.upper():10} {message}")

    def _pipeline_complete(self, result: pipeline.PipelineResult) -> None:
        self._set_busy(False)
        self.last_result = result
        self.last_diagnostics = result.diagnostics
        self.export_diagnostics_button.setEnabled(bool(self.last_diagnostics))
        self.selected_candidate = None
        self.status_label.setText(tr("Completed successfully"))
        self.status_label.setStyleSheet(f"color: {SUCCESS}; font-weight: 600;")
        output = result.merged_path or result.subtitle_path
        self.result_label.setText(Path(output).name)
        self.play_button.setVisible(bool(result.merged_path))
        self.result_frame.setVisible(True)
        if result.merged_path:
            self.preferences = self.settings_store.remember_media_file(
                result.merged_path
            )
        for warning in result.warnings:
            self._append_detail(f"WARNING    {warning}")
        self._refresh_recent()

    def _pipeline_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.status_label.setStyleSheet(f"color: {DANGER};")
        self.status_label.setText(tr("The operation could not be completed."))
        self._append_detail(f"ERROR      {error}")
        self.details_toggle.setChecked(True)
        if isinstance(error, pipeline.CandidateReviewRequired):
            self.status_label.setText(tr("Review Search Results"))
            self.status_label.setStyleSheet(f"color: {WARM}; font-weight: 600;")
            self._open_candidate_review(
                error.result,
                allow_translation=error.allow_translation,
                rejection_reasons=error.rejection_reasons,
            )
            return
        QMessageBox.critical(
            self,
            tr("Subtitle Preparation Failed"),
            tr("The operation could not be completed.")
            + "\n\n"
            + tr("Technical details:")
            + f"\n{error}",
        )

    def _pipeline_cancelled(self) -> None:
        self._set_busy(False)
        self.status_label.setStyleSheet(f"color: {WARM};")
        self.status_label.setText(tr("Operation cancelled."))
        self._append_detail("CANCELLED  Operation cancelled by user")

    def _pipeline_diagnostics_ready(self, report: dict[str, Any]) -> None:
        self.last_diagnostics = report
        self.export_diagnostics_button.setEnabled(bool(report))

    def _cancel_pipeline(self) -> None:
        worker = self._pipeline_worker
        if not worker or not worker.isRunning():
            return
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText(tr("Cancelling..."))
        self.status_label.setText(tr("Cancelling safely..."))
        self._append_detail("CANCEL     Cancellation requested")
        worker.cancel()

    def _set_busy(self, busy: bool) -> None:
        self.primary_button.setEnabled(not busy and bool(self.video_path))
        self.drop_frame.setEnabled(not busy)
        self.primary_button.setText(
            tr("Working...") if busy else tr("Prepare Subtitles")
        )
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setText(tr("Cancel"))
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setValue(2)
            self.status_label.setStyleSheet(f"color: {TEXT};")

    def _open_candidate_review(
        self,
        initial_result: open_subtitles.SubtitleSearchResult | None = None,
        *,
        allow_translation: bool = False,
        rejection_reasons: dict[int, str] | None = None,
    ) -> None:
        if not self.video_path:
            QMessageBox.information(
                self,
                tr("Choose Media"),
                tr("Choose a media file first."),
            )
            return
        try:
            key = self.secret_store.get(settings.OPEN_SUBTITLES_SECRET)
        except settings.SecretStorageError as exc:
            QMessageBox.critical(
                self,
                tr("Keychain Error"),
                tr("macOS Keychain reported an error: {error}").format(
                    error=exc
                ),
            )
            return
        if not key and not allow_translation:
            QMessageBox.information(
                self,
                tr("OpenSubtitles Key Required"),
                tr("Add an OpenSubtitles API key in Settings."),
            )
            self.tabs.setCurrentIndex(2)
            return
        self._candidate_dialog = CandidateDialog(
            self,
            api_key=key,
            video_path=self.video_path,
            target_language=self.target_combo.currentData(),
            initial_result=initial_result,
            allow_translation=allow_translation,
            translation_summary=self._translation_review_summary(),
            rejection_reasons=rejection_reasons,
        )
        self._candidate_dialog.candidate_chosen.connect(
            self._candidate_selected
        )
        self._candidate_dialog.translation_requested.connect(
            self._translate_after_review
        )
        self._candidate_dialog.exec()

    def _candidate_selected(
        self,
        candidate: open_subtitles.SubtitleCandidate,
    ) -> None:
        self.selected_candidate = candidate
        self.selected_subtitle_path = ""
        name = candidate.release_name or candidate.file_name
        self.sidecar_label.setText(
            tr("Target subtitle: {name}").format(name=name)
        )
        self._update_cost_estimate()

    def _translate_after_review(self) -> None:
        self.selected_candidate = None
        self.selected_subtitle_path = ""
        self.sidecar_label.setText(tr("Target subtitle: automatic"))
        self._append_detail("TRANSLATE  Approved after subtitle review")
        QTimer.singleShot(
            0,
            lambda: self._start_pipeline_for_strategy("translate"),
        )

    def _translation_review_summary(self) -> str:
        model = self.model_combo.currentText().strip()
        reasoning = str(self.reasoning_combo.currentData() or "")
        estimate = translation_cost.estimate_for_duration(
            self._media_duration_seconds,
            model,
            reasoning,
        )
        if estimate:
            range_text = (
                f"${estimate.cost_low:.2f}-${estimate.cost_high:.2f}"
            )
            return tr("Estimated translation cost: {range}").format(
                range=range_text
            )
        return tr("Pricing is unavailable for this custom model.")

    def _toggle_details(self, visible: bool) -> None:
        self.details.setVisible(visible)
        self.details_toggle.setArrowType(
            Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
        )

    def _append_detail(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.details.appendPlainText(f"{stamp}  {message}")

    def _play_result(self) -> None:
        if self.last_result and self.last_result.merged_path:
            self._launch_mpv(self.last_result.merged_path)

    def _reveal_result(self) -> None:
        if not self.last_result:
            return
        path = self.last_result.merged_path or self.last_result.subtitle_path
        if path:
            subprocess.run(  # noqa: S603
                ["/usr/bin/open", "-R", path],
                check=False,
            )

    def _export_diagnostics(self) -> None:
        if not self.last_diagnostics:
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        initial = (
            Path.home()
            / "Downloads"
            / f"SubtitleTranslator-Diagnostics-{timestamp}.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export Diagnostics"),
            str(initial),
            tr("JSON files") + " (*.json)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        report = dict(self.last_diagnostics)
        report["tools"] = app_diagnostics.collect_tool_versions()
        try:
            saved = app_diagnostics.write_report(destination, report)
        except OSError as exc:
            QMessageBox.critical(
                self,
                tr("Diagnostics Export Failed"),
                tr("The diagnostics report could not be saved: {error}").format(
                    error=exc
                ),
            )
            return
        QMessageBox.information(
            self,
            tr("Diagnostics Exported"),
            tr(
                "Saved {name}. The report excludes API keys, subtitle text, "
                "and full media paths."
            ).format(name=saved.name),
        )

    def _launch_mpv(self, path: str) -> None:
        try:
            media_launcher.launch_in_mpv(
                path,
                configured_path=self.preferences.get("mpv_path", ""),
            )
        except media_launcher.MpvLaunchError as exc:
            answer = QMessageBox.warning(
                self,
                tr("mpv Not Available"),
                tr("{error}\n\nOpen setup instructions?").format(error=exc),
                QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                MpvSetupDialog(self).exec()

    def _refresh_recent(self) -> None:
        if self._recent_worker and self._recent_worker.isRunning():
            return
        roots = list(self.preferences["media_locations"])
        files = list(self.preferences["recent_media_files"])
        self.recent_list.clear()
        self.recent_list.addItem(
            tr("Scanning approved media folders...")
        )
        worker = FunctionThread(
            lambda: media_launcher.recent_media_files(
                roots,
                files=files,
                limit=40,
            ),
            self,
        )
        self._recent_worker = worker
        worker.completed.connect(self._recent_ready)
        worker.failed.connect(
            lambda error: self.recent_list.addItem(
                tr("Media scan failed: {error}").format(error=error)
            )
        )
        self._start_background_worker(worker)

    def _recent_ready(self, paths: list[Path]) -> None:
        self.recent_list.clear()
        if not paths:
            self.recent_list.addItem(
                tr("No media found in approved folders")
            )
            return
        for path in paths:
            item_text = f"{path.name}\n{path.parent}"
            self.recent_list.addItem(item_text)
            self.recent_list.item(self.recent_list.count() - 1).setData(
                Qt.ItemDataRole.UserRole,
                str(path),
            )

    def _selected_recent_path(self) -> str:
        item = self.recent_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _load_recent(self) -> None:
        path = self._selected_recent_path()
        if path:
            self.tabs.setCurrentIndex(0)
            self._select_media(path)

    def _play_recent(self) -> None:
        path = self._selected_recent_path()
        if path:
            self._launch_mpv(path)

    def _tab_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_recent()

    def _save_keys(self) -> None:
        try:
            if self.openai_key.text().strip():
                self.secret_store.set(
                    settings.OPENAI_SECRET,
                    self.openai_key.text(),
                )
                with suppress(OSError):
                    settings.remove_legacy_credential(
                        settings.OPENAI_SECRET
                    )
            if self.os_key.text().strip():
                self.secret_store.set(
                    settings.OPEN_SUBTITLES_SECRET,
                    self.os_key.text(),
                )
                with suppress(OSError):
                    settings.remove_legacy_credential(
                        settings.OPEN_SUBTITLES_SECRET
                    )
        except settings.SecretStorageError as exc:
            QMessageBox.critical(
                self,
                tr("Keychain Error"),
                tr("macOS Keychain reported an error: {error}").format(
                    error=exc
                ),
            )
            return
        self.openai_key.clear()
        self.os_key.clear()
        self.settings_store.save(self.preferences)
        self._update_key_states()
        QMessageBox.information(
            self,
            tr("API Credentials Saved"),
            tr("Credentials were saved to macOS Keychain."),
        )

    def _forget_keys(self) -> None:
        answer = QMessageBox.warning(
            self,
            tr("Remove API Keys"),
            tr("Remove both API credentials from macOS Keychain?"),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.secret_store.delete(settings.OPENAI_SECRET)
            self.secret_store.delete(settings.OPEN_SUBTITLES_SECRET)
        except settings.SecretStorageError as exc:
            QMessageBox.critical(
                self,
                tr("Keychain Error"),
                tr("macOS Keychain reported an error: {error}").format(
                    error=exc
                ),
            )
            return
        self._update_key_states()

    def _update_key_states(self) -> None:
        try:
            openai_present = self.secret_store.has(settings.OPENAI_SECRET)
            os_present = self.secret_store.has(
                settings.OPEN_SUBTITLES_SECRET
            )
        except settings.SecretStorageError:
            openai_present = os_present = False
        self.openai_state.setText(
            tr("Stored in Keychain")
            if openai_present
            else tr("Not configured")
        )
        self.os_state.setText(
            tr("Stored in Keychain")
            if os_present
            else tr("Not configured")
        )
        self.openai_state.setStyleSheet(
            f"color: {SUCCESS if openai_present else MUTED};"
        )
        self.os_state.setStyleSheet(
            f"color: {SUCCESS if os_present else MUTED};"
        )

    def _test_openai(self) -> None:
        key = self.openai_key.text().strip()
        if not key:
            try:
                key = self.secret_store.get(settings.OPENAI_SECRET)
            except settings.SecretStorageError as exc:
                QMessageBox.critical(
                    self,
                    tr("Keychain Error"),
                    tr("macOS Keychain reported an error: {error}").format(
                        error=exc
                    ),
                )
                return
        model = self.model_combo.currentText().strip()
        self.openai_state.setText(tr("Testing..."))
        worker = FunctionThread(
            lambda: translator.test_api_key(key, model),
            self,
        )
        worker.completed.connect(
            lambda _result: self._connection_test_ready(
                self.openai_state,
                tr("OpenAI connection ready"),
            )
        )
        worker.failed.connect(
            lambda error: self._connection_test_failed(self.openai_state, error)
        )
        self._start_background_worker(worker)

    def _test_opensubtitles(self) -> None:
        key = self.os_key.text().strip()
        if not key:
            try:
                key = self.secret_store.get(settings.OPEN_SUBTITLES_SECRET)
            except settings.SecretStorageError as exc:
                QMessageBox.critical(
                    self,
                    tr("Keychain Error"),
                    tr("macOS Keychain reported an error: {error}").format(
                        error=exc
                    ),
                )
                return
        self.os_state.setText(tr("Testing..."))
        worker = FunctionThread(
            lambda: open_subtitles.test_api_key(key),
            self,
        )
        worker.completed.connect(
            lambda _result: self._connection_test_ready(
                self.os_state,
                tr("OpenSubtitles connection ready"),
            )
        )
        worker.failed.connect(
            lambda error: self._connection_test_failed(self.os_state, error)
        )
        self._start_background_worker(worker)

    @staticmethod
    def _connection_test_ready(label: QLabel, text: str) -> None:
        label.setText(text)
        label.setStyleSheet(f"color: {SUCCESS};")

    @staticmethod
    def _connection_test_failed(label: QLabel, error: Exception) -> None:
        label.setText(
            tr("Connection failed: {error}").format(error=error)
        )
        label.setStyleSheet(f"color: {DANGER};")

    def _add_media_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            tr("Add Media Folder"),
            str(Path.home() / "Downloads"),
        )
        if not directory:
            return
        self.preferences = self.settings_store.add_media_location(directory)
        self._load_media_locations()

    def _remove_media_location(self) -> None:
        item = self.media_locations.currentItem()
        if not item:
            return
        path = item.text()
        locations = [
            location
            for location in self.preferences["media_locations"]
            if location != path
        ]
        self.preferences["media_locations"] = locations
        self.settings_store.save(self.preferences)
        self._load_media_locations()

    def _load_media_locations(self) -> None:
        self.media_locations.clear()
        self.media_locations.addItems(self.preferences["media_locations"])

    def _choose_workspace(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            tr("Choose Working Folder"),
            self.workspace_edit.text() or str(settings.WORKSPACE_DIR),
        )
        if directory:
            self.workspace_edit.setText(directory)

    def _open_workspace(self) -> None:
        path = Path(self.workspace_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(  # noqa: S603
            ["/usr/bin/open", str(path)],
            check=False,
        )

    def _choose_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            tr("Choose Output Folder"),
            self.custom_output_edit.text() or str(Path.home()),
        )
        if directory:
            self.custom_output_edit.setText(directory)

    def _output_mode_changed(self) -> None:
        custom = self.output_mode_combo.currentData() == "custom"
        self.custom_output_edit.setEnabled(custom)

    def _choose_mpv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Choose mpv Executable"),
            "/Applications",
            tr("All Files") + " (*)",
        )
        if path:
            self.mpv_path_edit.setText(path)

    def _apply_quality_preset(self, preset: str) -> None:
        values = translation_cost.QUALITY_PRESETS.get(preset)
        if not values:
            return
        model, reasoning = values
        self._setting_translation_controls = True
        self.model_combo.setCurrentText(model)
        _set_combo_data(self.reasoning_combo, reasoning)
        self._setting_translation_controls = False
        self._sync_quality_buttons()
        self._update_cost_estimate()

    def _advanced_translation_changed(self, *_args: object) -> None:
        if self._setting_translation_controls:
            return
        self._sync_quality_buttons()
        self._update_cost_estimate()

    def _sync_quality_buttons(self) -> None:
        preset = translation_cost.preset_for(
            self.model_combo.currentText().strip(),
            str(self.reasoning_combo.currentData() or ""),
        )
        for code, button in self.quality_buttons.items():
            button.setChecked(code == preset)
        self.quality_state.setText(
            tr("Custom") if preset == "custom" else ""
        )

    def _update_cost_estimate(self, *_args: object) -> None:
        if not hasattr(self, "cost_label"):
            return
        model = self.model_combo.currentText().strip()
        reasoning = str(self.reasoning_combo.currentData() or "")
        rates = translation_cost.MODEL_PRICING_PER_MILLION.get(model)
        if rates:
            input_rate, output_rate = rates
            price_text = tr(
                "Standard price: ${input_rate:g} input / "
                "${output_rate:g} output per 1M tokens."
            ).format(
                input_rate=input_rate,
                output_rate=output_rate,
            )
        else:
            price_text = tr("Pricing is unavailable for this custom model.")

        method = next(
            (
                code
                for code, button in self.mode_buttons.items()
                if button.isChecked()
            ),
            "automatic",
        )
        translation_possible = (
            method != "find"
            and not self.selected_subtitle_path
            and self.selected_candidate is None
        )
        estimate = (
            translation_cost.estimate_for_duration(
                self._media_duration_seconds,
                model,
                reasoning,
            )
            if self._media_duration_seconds > 0 and translation_possible
            else None
        )
        if not translation_possible:
            prepare_text = tr("No OpenAI translation cost for this method.")
        elif estimate:
            range_text = (
                f"${estimate.cost_low:.2f}-${estimate.cost_high:.2f}"
            )
            prepare_text = (
                tr("Estimated translation cost: {range}").format(
                    range=range_text
                )
                if method == "translate"
                else tr("If translation is needed: about {range}").format(
                    range=range_text
                )
            )
        else:
            prepare_text = tr(
                "Translation estimate appears after media inspection."
            )
        self.cost_label.setText(prepare_text)
        self.settings_cost_label.setText(f"{price_text}  {prepare_text}")

    def _load_prompt_editor(self) -> None:
        if not hasattr(self, "prompt_language_combo"):
            return
        code = self.prompt_language_combo.currentData()
        if not code:
            return
        override = self.preferences.get("prompt_overrides", {}).get(code)
        self.prompt_editor.setPlainText(
            override or languages.default_prompt_template(code)
        )

    def _reset_prompt(self) -> None:
        code = self.prompt_language_combo.currentData()
        self.prompt_editor.setPlainText(languages.default_prompt_template(code))

    def _save_prompt(self) -> None:
        code = self.prompt_language_combo.currentData()
        prompt = self.prompt_editor.toPlainText()
        valid, message = languages.validate_prompt_template(prompt)
        if not valid:
            QMessageBox.warning(
                self,
                tr("Prompt Needs Attention"),
                tr("The prompt is not valid: {error}").format(
                    error=_localized_prompt_error(message)
                ),
            )
            return
        default = languages.default_prompt_template(code).strip()
        overrides = dict(self.preferences["prompt_overrides"])
        if prompt.strip() == default:
            overrides.pop(code, None)
        else:
            overrides[code] = prompt
        self.preferences["prompt_overrides"] = overrides
        self.settings_store.save(self.preferences)
        QMessageBox.information(
            self,
            tr("Prompt Saved"),
            tr("Language prompt updated."),
        )

    def _save_preferences(self, *, silent: bool = False) -> None:
        previous_interface_language = self.preferences.get(
            "interface_language",
            "system",
        )
        interface_language = self.interface_combo.currentData() or "system"
        self.preferences.update(
            {
                "workspace_directory": self.workspace_edit.text().strip()
                or str(settings.WORKSPACE_DIR),
                "output_mode": self.output_mode_combo.currentData(),
                "custom_output_directory": self.custom_output_edit.text().strip(),
                "target_language": self.target_combo.currentData(),
                "source_language": self.source_combo.currentData(),
                "translation_model": self.model_combo.currentText().strip()
                or "gpt-5.6-luna",
                "reasoning_effort": self.reasoning_combo.currentData(),
                "quality_preset": translation_cost.preset_for(
                    self.model_combo.currentText().strip(),
                    str(self.reasoning_combo.currentData() or ""),
                ),
                "cleanup_intermediates": self.clean_checkbox.isChecked(),
                "mpv_path": self.mpv_path_edit.text().strip(),
                "interface_language": interface_language,
            }
        )
        self.settings_store.save(self.preferences)
        settings.ensure_private_directories(
            self.preferences["workspace_directory"]
        )
        if not silent:
            message = tr("Preferences updated.")
            if interface_language != previous_interface_language:
                message += "\n\n" + tr(
                    "Restart SubtitleTranslator to apply the new interface "
                    "language."
                )
            QMessageBox.information(
                self,
                tr("Settings Saved"),
                message,
            )

    def _update_dependency_status(self) -> None:
        statuses = dependencies.dependency_status()
        parts = [
            tr("{tool}: {state}").format(
                tool=item.name,
                state=tr("ready") if item.available else tr("missing"),
            )
            for item in statuses
        ]
        required_ready = all(
            item.available for item in statuses if item.required
        )
        self.dependency_label.setText("  |  ".join(parts))
        self.dependency_label.setStyleSheet(
            f"color: {SUCCESS if required_ready else WARM};"
        )

    def _show_dependency_setup(self) -> None:
        DependencySetupDialog(self, include_mpv=True).exec()
        self._update_dependency_status()

    def _show_setup_checklist(self) -> None:
        SetupChecklistDialog(self).exec()
        self._update_dependency_status()
        self._update_key_states()

    def _show_first_run(self) -> None:
        self._show_setup_checklist()

    def _show_privacy(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("Privacy"))
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(tr("The developer does not collect your data"))
        dialog.setInformativeText(
            tr("API credentials stay in macOS Keychain.")
            + " "
            + tr("Subtitle processing and media files stay on this Mac.")
            + " "
            + tr(
                "OpenAI receives subtitle text only when you translate."
            )
            + " "
            + tr(
                "OpenSubtitles receives search metadata only when you search."
            )
            + " "
            + tr("Requests go directly to those providers.")
        )
        docs = dialog.addButton(
            tr("Privacy Document"),
            QMessageBox.ButtonRole.ActionRole,
        )
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        if dialog.clickedButton() == docs:
            QDesktopServices.openUrl(QUrl(PRIVACY_URL))


def _set_combo_data(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
