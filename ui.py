"""Modern Qt interface for SubtitleTranslator."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
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
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
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
import languages
import media_launcher
import open_subtitles
import pipeline
import settings
import translator


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
PRIVACY_URL = "https://github.com/daniel-p-berg/SubtitleTranslator/blob/main/PRIVACY.md"


def apply_application_style(application: QApplication) -> None:
    """Apply a restrained dark utility theme with native dimensions."""
    application.setStyle("Fusion")
    application.setStyleSheet(
        f"""
        * {{
            font-family: "Avenir Next", "Helvetica Neue", sans-serif;
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
        self.title = QLabel("Choose a media file")
        self.title.setStyleSheet("font-size: 17px; font-weight: 650;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel("MKV, MP4, MOV, M4V, AVI, WebM, TS, or M2TS")
        self.detail.setStyleSheet(f"color: {MUTED};")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        self.choose = QPushButton("Open File")
        self.choose.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        self.choose.setFixedWidth(120)
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
            size_text = f"{size_gb:.2f} GB"
        except OSError:
            size_text = "Size unavailable"
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
            "Choose Media",
            str(Path.home() / "Downloads"),
            "Media (*.mkv *.mp4 *.m4v *.mov *.avi *.webm *.ts *.m2ts)",
        )
        if path:
            self.file_selected.emit(path)


class FunctionThread(QThread):
    """Execute a callable without blocking Qt's event loop."""

    completed = Signal(object)
    failed = Signal(object)

    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
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

    def __init__(self, options: pipeline.PipelineOptions) -> None:
        super().__init__()
        self.options = options

    def run(self) -> None:
        try:
            worker = pipeline.SubtitlePipeline(
                lambda stage, message, percent: self.progress.emit(
                    stage,
                    message,
                    percent,
                )
            )
            self.completed.emit(worker.run(self.options))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(exc)


class CandidateDialog(QDialog):
    """Manual OpenSubtitles result review with editable search terms."""

    candidate_chosen = Signal(object)

    def __init__(
        self,
        parent: QWidget,
        *,
        api_key: str,
        video_path: str,
        target_language: str,
        initial_result: open_subtitles.SubtitleSearchResult | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.video_path = video_path
        self.target_language = target_language
        self._candidates: list[open_subtitles.SubtitleCandidate] = []
        self._thread: FunctionThread | None = None

        target = languages.get_language(target_language)
        self.setWindowTitle(f"Review {target.name} Results")
        self.resize(780, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(f"OpenSubtitles results  /  {target.name}")
        title.setStyleSheet("font-size: 18px; font-weight: 650;")
        layout.addWidget(title)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Movie or episode title")
        self.search_button = QPushButton("Search")
        self.search_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.search_button.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Release", "Title", "Year", "Rating", "Downloads"]
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
        self.table.itemDoubleClicked.connect(lambda _item: self._use_selected())
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.use_button = buttons.addButton(
            "Use Selected",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
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
        query = self.query.text().strip() or None
        self.search_button.setEnabled(False)
        self.status.setText("Searching...")
        worker = pipeline.SubtitlePipeline()
        self._thread = FunctionThread(
            lambda: worker.search(
                self.api_key,
                self.video_path,
                self.target_language,
                query_override=query,
            )
        )
        self._thread.completed.connect(self._populate)
        self._thread.failed.connect(self._search_failed)
        self._thread.start()

    def _populate(self, result: open_subtitles.SubtitleSearchResult) -> None:
        self.search_button.setEnabled(True)
        self.query.setText(result.query)
        self._candidates = list(result.candidates)
        self.table.setRowCount(len(self._candidates))
        automatic_ids = {item.file_id for item in result.automatic_matches}
        for row, candidate in enumerate(self._candidates):
            release = QTableWidgetItem(candidate.release_name or candidate.file_name)
            if candidate.file_id in automatic_ids:
                release.setForeground(ACCENT)
                release.setToolTip("Strong automatic title match")
            elif candidate.trusted:
                release.setForeground(WARM)
                release.setToolTip("Trusted uploader; review title and cut")
            self.table.setItem(row, 0, release)
            self.table.setItem(row, 1, QTableWidgetItem(candidate.feature_title))
            self.table.setItem(row, 2, QTableWidgetItem(candidate.feature_year))
            self.table.setItem(row, 3, QTableWidgetItem(f"{candidate.rating:g}"))
            self.table.setItem(
                row,
                4,
                QTableWidgetItem(f"{candidate.download_count:,}"),
            )
        self.status.setText(
            f"{len(self._candidates)} result(s); "
            f"{len(result.automatic_matches)} strong title match(es)"
        )
        if self._candidates:
            self.table.selectRow(0)

    def _search_failed(self, error: Exception) -> None:
        self.search_button.setEnabled(True)
        self.status.setText(str(error))

    def _use_selected(self) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self._candidates):
            return
        self.candidate_chosen.emit(self._candidates[row])
        self.accept()


class MpvSetupDialog(QDialog):
    """Concise mpv installation and dual-subtitle configuration."""

    CONFIG_TEXT = """# SubtitleTranslator dual-subtitle layout
sub-pos=88
secondary-sub-pos=12
"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("mpv Setup")
        self.resize(610, 430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("mpv dual subtitles")
        title.setStyleSheet("font-size: 19px; font-weight: 650;")
        layout.addWidget(title)

        status = dependencies.resolve_tool("mpv")
        state = QLabel(
            f"Detected: {status}"
            if status
            else "mpv was not detected on this Mac."
        )
        state.setStyleSheet(f"color: {SUCCESS if status else WARM};")
        state.setWordWrap(True)
        layout.addWidget(state)

        install = QLabel(
            "Install with Homebrew using <b>brew install mpv</b>. "
            "Configuration lives at <b>~/.config/mpv/mpv.conf</b>."
        )
        install.setWordWrap(True)
        layout.addWidget(install)

        config = QPlainTextEdit(self.CONFIG_TEXT)
        config.setReadOnly(True)
        config.setMaximumHeight(110)
        layout.addWidget(config)

        controls = QLabel(
            "<b>g-s</b> selects the primary track, <b>g-S</b> selects the "
            "secondary track, and <b>Alt+v</b> toggles the secondary subtitle."
        )
        controls.setWordWrap(True)
        layout.addWidget(controls)

        row = QHBoxLayout()
        copy_button = QPushButton("Copy Configuration")
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(self.CONFIG_TEXT)
        )
        docs_button = QPushButton("mpv Installation")
        docs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(MPV_INSTALL_URL))
        )
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        row.addWidget(copy_button)
        row.addWidget(docs_button)
        row.addStretch()
        row.addWidget(close_button)
        layout.addLayout(row)


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self, version: str) -> None:
        super().__init__()
        self.version = version
        self.settings_store = settings.SettingsStore()
        self.secret_store = settings.SecretStore()
        self.preferences = self.settings_store.load()
        self.video_path = ""
        self.selected_subtitle_path = ""
        self.selected_candidate: open_subtitles.SubtitleCandidate | None = None
        self.last_result: pipeline.PipelineResult | None = None
        self._worker: QThread | None = None
        self._candidate_dialog: CandidateDialog | None = None
        self._first_run = (
            not settings.SETTINGS_PATH.exists()
            and os.environ.get("SUBTITLE_TRANSLATOR_SMOKE_TEST") != "1"
        )

        settings.ensure_private_directories(
            self.preferences["workspace_directory"]
        )
        if os.environ.get("SUBTITLE_TRANSLATOR_SMOKE_TEST") != "1":
            self._migrate_legacy_credentials()

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
        privacy = QPushButton("Privacy")
        privacy.setToolTip("View the local-data and network privacy model")
        privacy.clicked.connect(self._show_privacy)
        mpv_button = QPushButton("mpv Setup")
        mpv_button.clicked.connect(lambda: MpvSetupDialog(self).exec())
        header.addWidget(brand)
        header.addWidget(version)
        header.addStretch()
        header.addWidget(mpv_button)
        header.addWidget(privacy)
        root_layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_prepare_tab(), "Prepare")
        self.tabs.addTab(self._build_recent_tab(), "Recent")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.currentChanged.connect(self._tab_changed)
        root_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def _build_prepare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        self.drop_frame = DropFrame()
        self.drop_frame.file_selected.connect(self._select_media)
        layout.addWidget(self.drop_frame)

        self.inspect_label = QLabel("No media selected")
        self.inspect_label.setStyleSheet(f"color: {MUTED};")
        self.inspect_label.setWordWrap(True)
        layout.addWidget(self.inspect_label)

        controls = QGroupBox("LANGUAGES AND METHOD")
        control_grid = QGridLayout(controls)
        control_grid.setHorizontalSpacing(14)
        control_grid.setVerticalSpacing(11)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Auto-detect", "auto")
        self.target_combo = QComboBox()
        for language in languages.all_languages():
            self.source_combo.addItem(language.name, language.code)
            self.target_combo.addItem(language.name, language.code)
        control_grid.addWidget(QLabel("Source"), 0, 0)
        control_grid.addWidget(self.source_combo, 1, 0)
        control_grid.addWidget(QLabel("Target"), 0, 1)
        control_grid.addWidget(self.target_combo, 1, 1)

        mode_label = QLabel("Method")
        control_grid.addWidget(mode_label, 2, 0)
        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QToolButton] = {}
        for index, (code, label) in enumerate(
            (
                ("automatic", "Automatic"),
                ("find", "Find"),
                ("translate", "Translate"),
            )
        ):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setObjectName("modeButton")
            button.setMinimumHeight(34)
            if index == 0:
                button.setChecked(True)
            self.mode_group.addButton(button)
            self.mode_buttons[code] = button
            mode_row.addWidget(button)
        mode_row.addStretch()
        review_button = QPushButton("Review Search Results")
        review_button.setMinimumHeight(34)
        review_button.clicked.connect(self._open_candidate_review)
        mode_row.addWidget(review_button)
        control_grid.addLayout(mode_row, 3, 0, 1, 2)
        control_grid.setRowMinimumHeight(3, 42)

        sidecar_container = QFrame()
        sidecar_row = QHBoxLayout(sidecar_container)
        sidecar_row.setContentsMargins(4, 0, 4, 0)
        self.sidecar_label = QLabel("Target subtitle: automatic")
        self.sidecar_label.setStyleSheet(f"color: {MUTED};")
        choose_sidecar = QPushButton("Choose Subtitle")
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
        clear_sidecar.setToolTip("Clear selected subtitle")
        clear_sidecar.clicked.connect(self._clear_sidecar)
        sidecar_row.addWidget(self.sidecar_label, 1)
        sidecar_row.addWidget(choose_sidecar)
        sidecar_row.addWidget(clear_sidecar)
        layout.addWidget(controls)
        layout.addWidget(sidecar_container)

        output_group = QGroupBox("OUTPUT")
        output_layout = QGridLayout(output_group)
        self.merge_checkbox = QCheckBox("Create merged MKV")
        self.merge_checkbox.setChecked(True)
        self.keep_srt_checkbox = QCheckBox("Keep final SRT")
        self.keep_srt_checkbox.setChecked(True)
        self.clean_checkbox = QCheckBox("Clean working files after success")
        self.delete_original_checkbox = QCheckBox(
            "Move original to Trash after verified merge"
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
        self.primary_button = QPushButton("Prepare Subtitles")
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setEnabled(False)
        self.primary_button.clicked.connect(self._start_pipeline)
        action_row.addStretch()
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
        self.details_toggle.setText("Details")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.details_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.details_toggle.toggled.connect(self._toggle_details)
        layout.addWidget(self.details_toggle, alignment=Qt.AlignmentFlag.AlignLeft)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumBlockCount(500)
        self.details.setVisible(False)
        self.details.setMinimumHeight(110)
        layout.addWidget(self.details)

        self.result_frame = QFrame()
        result_layout = QHBoxLayout(self.result_frame)
        result_layout.setContentsMargins(0, 4, 0, 0)
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.play_button = QPushButton("Play in mpv")
        self.play_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.play_button.clicked.connect(self._play_result)
        self.reveal_button = QPushButton("Show in Finder")
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
        return page

    def _build_recent_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Recent media")
        title.setStyleSheet("font-size: 18px; font-weight: 650;")
        refresh = QPushButton("Refresh")
        refresh.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        refresh.clicked.connect(self._refresh_recent)
        add_folder = QPushButton("Add Media Folder")
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
        load = QPushButton("Load in Prepare")
        load.clicked.connect(self._load_recent)
        play = QPushButton("Play in mpv")
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

        api_group = QGroupBox("API CONNECTIONS")
        api_layout = QGridLayout(api_group)
        self.openai_key = QLineEdit()
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setPlaceholderText("Stored in macOS Keychain")
        self.os_key = QLineEdit()
        self.os_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.os_key.setPlaceholderText("Stored in macOS Keychain")
        self.openai_state = QLabel("")
        self.os_state = QLabel("")
        test_openai = QPushButton("Test")
        test_openai.clicked.connect(self._test_openai)
        test_os = QPushButton("Test")
        test_os.clicked.connect(self._test_opensubtitles)
        openai_link = QToolButton()
        openai_link.setText("Get Key")
        openai_link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(OPENAI_URL))
        )
        os_link = QToolButton()
        os_link.setText("Get Key")
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
        save_keys = QPushButton("Save Keys to Keychain")
        save_keys.clicked.connect(self._save_keys)
        forget_keys = QPushButton("Forget Keys")
        forget_keys.setObjectName("dangerButton")
        forget_keys.clicked.connect(self._forget_keys)
        key_buttons = QHBoxLayout()
        key_buttons.addStretch()
        key_buttons.addWidget(forget_keys)
        key_buttons.addWidget(save_keys)
        api_layout.addLayout(key_buttons, 4, 0, 1, 4)
        layout.addWidget(api_group)

        files_group = QGroupBox("FILES")
        files_layout = QGridLayout(files_group)
        self.media_locations = QListWidget()
        self.media_locations.setMaximumHeight(105)
        media_buttons = QVBoxLayout()
        add_media = QToolButton()
        add_media.setText("Add")
        add_media.clicked.connect(self._add_media_location)
        remove_media = QToolButton()
        remove_media.setText("Remove")
        remove_media.clicked.connect(self._remove_media_location)
        media_buttons.addWidget(add_media)
        media_buttons.addWidget(remove_media)
        media_buttons.addStretch()
        files_layout.addWidget(QLabel("Media folders"), 0, 0)
        files_layout.addWidget(self.media_locations, 1, 0, 1, 3)
        files_layout.addLayout(media_buttons, 1, 3)

        self.workspace_edit = QLineEdit()
        workspace_browse = QToolButton()
        workspace_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        workspace_browse.setToolTip("Choose working folder")
        workspace_browse.clicked.connect(self._choose_workspace)
        workspace_open = QToolButton()
        workspace_open.setText("Open")
        workspace_open.clicked.connect(self._open_workspace)
        files_layout.addWidget(QLabel("Working folder"), 2, 0)
        files_layout.addWidget(self.workspace_edit, 2, 1)
        files_layout.addWidget(workspace_browse, 2, 2)
        files_layout.addWidget(workspace_open, 2, 3)

        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem("Beside original media", "alongside")
        self.output_mode_combo.addItem("Custom folder", "custom")
        self.output_mode_combo.currentIndexChanged.connect(
            self._output_mode_changed
        )
        self.custom_output_edit = QLineEdit()
        output_browse = QToolButton()
        output_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        output_browse.setToolTip("Choose output folder")
        output_browse.clicked.connect(self._choose_output)
        files_layout.addWidget(QLabel("Default output"), 3, 0)
        files_layout.addWidget(self.output_mode_combo, 3, 1)
        files_layout.addWidget(self.custom_output_edit, 4, 1)
        files_layout.addWidget(output_browse, 4, 2)
        layout.addWidget(files_group)

        translation_group = QGroupBox("TRANSLATION")
        translation_layout = QGridLayout(translation_group)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(
            ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
        )
        self.reasoning_combo = QComboBox()
        self.reasoning_combo.addItems(
            ["none", "low", "medium", "high", "xhigh", "max"]
        )
        translation_layout.addWidget(QLabel("OpenAI model"), 0, 0)
        translation_layout.addWidget(self.model_combo, 0, 1)
        translation_layout.addWidget(QLabel("Reasoning"), 0, 2)
        translation_layout.addWidget(self.reasoning_combo, 0, 3)

        self.prompt_language_combo = QComboBox()
        for language in languages.all_languages():
            self.prompt_language_combo.addItem(language.name, language.code)
        self.prompt_language_combo.currentIndexChanged.connect(
            self._load_prompt_editor
        )
        translation_layout.addWidget(QLabel("Prompt profile"), 1, 0)
        translation_layout.addWidget(self.prompt_language_combo, 1, 1, 1, 3)
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setMinimumHeight(210)
        translation_layout.addWidget(self.prompt_editor, 2, 0, 1, 4)
        prompt_buttons = QHBoxLayout()
        reset_prompt = QPushButton("Reset Default")
        reset_prompt.clicked.connect(self._reset_prompt)
        save_prompt = QPushButton("Save Prompt")
        save_prompt.clicked.connect(self._save_prompt)
        prompt_buttons.addStretch()
        prompt_buttons.addWidget(reset_prompt)
        prompt_buttons.addWidget(save_prompt)
        translation_layout.addLayout(prompt_buttons, 3, 0, 1, 4)
        layout.addWidget(translation_group)

        playback_group = QGroupBox("PLAYBACK")
        playback_layout = QGridLayout(playback_group)
        self.mpv_path_edit = QLineEdit()
        self.mpv_path_edit.setPlaceholderText("Auto-detect mpv")
        mpv_browse = QToolButton()
        mpv_browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        mpv_browse.setToolTip("Choose mpv executable")
        mpv_browse.clicked.connect(self._choose_mpv)
        setup = QPushButton("Dual Subtitle Setup")
        setup.clicked.connect(lambda: MpvSetupDialog(self).exec())
        playback_layout.addWidget(QLabel("mpv executable"), 0, 0)
        playback_layout.addWidget(self.mpv_path_edit, 0, 1)
        playback_layout.addWidget(mpv_browse, 0, 2)
        playback_layout.addWidget(setup, 1, 1, 1, 2)
        layout.addWidget(playback_group)

        dependency_group = QGroupBox("LOCAL TOOLS")
        dependency_layout = QVBoxLayout(dependency_group)
        self.dependency_label = QLabel("")
        self.dependency_label.setWordWrap(True)
        dependency_layout.addWidget(self.dependency_label)
        check_dependencies = QPushButton("Check Again")
        check_dependencies.clicked.connect(self._update_dependency_status)
        dependency_layout.addWidget(
            check_dependencies,
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        layout.addWidget(dependency_group)

        save_settings = QPushButton("Save Settings")
        save_settings.setObjectName("primaryButton")
        save_settings.clicked.connect(self._save_preferences)
        layout.addWidget(save_settings, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addStretch()

        scroll.setWidget(content)
        return scroll

    def _load_preferences_into_ui(self) -> None:
        _set_combo_data(self.target_combo, self.preferences["target_language"])
        _set_combo_data(self.source_combo, self.preferences["source_language"])
        self.clean_checkbox.setChecked(self.preferences["cleanup_intermediates"])
        self.workspace_edit.setText(self.preferences["workspace_directory"])
        _set_combo_data(self.output_mode_combo, self.preferences["output_mode"])
        self.custom_output_edit.setText(
            self.preferences["custom_output_directory"]
        )
        self.model_combo.setCurrentText(self.preferences["translation_model"])
        self.reasoning_combo.setCurrentText(self.preferences["reasoning_effort"])
        self.mpv_path_edit.setText(self.preferences["mpv_path"])
        self.media_locations.clear()
        self.media_locations.addItems(self.preferences["media_locations"])
        self._load_prompt_editor()
        self._output_mode_changed()
        self._update_key_states()
        self._update_dependency_status()

    def _select_media(self, path: str) -> None:
        media = Path(path).expanduser().resolve()
        if not media.is_file() or media.suffix.lower() not in app_paths.VIDEO_EXTENSIONS:
            QMessageBox.warning(self, "Unsupported File", "Choose a supported media file.")
            return
        self.video_path = str(media)
        self.selected_subtitle_path = ""
        self.selected_candidate = None
        self.sidecar_label.setText("Target subtitle: automatic")
        self.drop_frame.set_media(self.video_path)
        self.primary_button.setEnabled(True)
        self.result_frame.setVisible(False)
        self.inspect_label.setText("Inspecting subtitle tracks...")
        self.preferences = self.settings_store.remember_media_location(media.parent)
        self._load_media_locations()

        target = self.target_combo.currentData()
        roots = list(self.preferences["media_locations"])
        self._worker = FunctionThread(
            lambda: pipeline.SubtitlePipeline().inspect(
                self.video_path,
                target_language=target,
                media_roots=roots,
            )
        )
        self._worker.completed.connect(self._inspection_complete)
        self._worker.failed.connect(self._inspection_failed)
        self._worker.start()

    def _inspection_complete(self, inspection: pipeline.MediaInspection) -> None:
        text_count = sum(1 for track in inspection.tracks if track.text_based)
        image_count = len(inspection.tracks) - text_count
        source = (
            languages.get_language(inspection.suggested_source_language).name
            if inspection.suggested_source_language != "auto"
            else "not identified"
        )
        target_state = "target found" if inspection.target_available else "target not found"
        self.inspect_label.setText(
            f"{text_count} text track(s), {image_count} image track(s), "
            f"{len(inspection.sidecars)} sidecar(s)  |  source {source}  |  "
            f"{target_state}"
        )
        if (
            self.source_combo.currentData() == "auto"
            and inspection.suggested_source_language != "auto"
        ):
            _set_combo_data(
                self.source_combo,
                inspection.suggested_source_language,
            )

    def _inspection_failed(self, error: Exception) -> None:
        self.inspect_label.setText(f"Subtitle inspection unavailable: {error}")

    def _choose_sidecar(self) -> None:
        initial = str(Path(self.video_path).parent) if self.video_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Target Subtitle",
            initial,
            "Subtitles (*.srt *.ass *.ssa *.vtt)",
        )
        if path:
            self.selected_subtitle_path = path
            self.selected_candidate = None
            self.sidecar_label.setText(f"Target subtitle: {Path(path).name}")

    def _clear_sidecar(self) -> None:
        self.selected_subtitle_path = ""
        self.selected_candidate = None
        self.sidecar_label.setText("Target subtitle: automatic")

    def _start_pipeline(self) -> None:
        if not self.video_path or (self._worker and self._worker.isRunning()):
            return
        if not self.merge_checkbox.isChecked() and not self.keep_srt_checkbox.isChecked():
            QMessageBox.warning(
                self,
                "No Output Selected",
                "Select a merged MKV, a final SRT, or both.",
            )
            return
        if self.delete_original_checkbox.isChecked():
            answer = QMessageBox.warning(
                self,
                "Move Original to Trash",
                "After the merged MKV passes verification, the original media "
                "will be moved to Trash. Continue?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._save_preferences(silent=True)
        try:
            openai_key = self.secret_store.get(settings.OPENAI_SECRET)
            os_key = self.secret_store.get(settings.OPEN_SUBTITLES_SECRET)
        except settings.SecretStorageError as exc:
            QMessageBox.critical(self, "Keychain Error", str(exc))
            return

        method = next(
            code for code, button in self.mode_buttons.items() if button.isChecked()
        )
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
        self._append_detail("Job started")
        self._worker = PipelineThread(options)
        self._worker.progress.connect(self._pipeline_progress)
        self._worker.completed.connect(self._pipeline_complete)
        self._worker.failed.connect(self._pipeline_failed)
        self._worker.start()

    def _pipeline_progress(self, stage: str, message: str, percent: int) -> None:
        if percent:
            self.progress_bar.setValue(percent)
        self.status_label.setText(message)
        self._append_detail(f"{stage.upper():10} {message}")

    def _pipeline_complete(self, result: pipeline.PipelineResult) -> None:
        self._set_busy(False)
        self.last_result = result
        self.selected_candidate = None
        self.status_label.setText("Completed successfully")
        self.status_label.setStyleSheet(f"color: {SUCCESS}; font-weight: 600;")
        output = result.merged_path or result.subtitle_path
        self.result_label.setText(Path(output).name)
        self.play_button.setVisible(bool(result.merged_path))
        self.result_frame.setVisible(True)
        for warning in result.warnings:
            self._append_detail(f"WARNING    {warning}")
        self._refresh_recent()

    def _pipeline_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.status_label.setStyleSheet(f"color: {DANGER};")
        self.status_label.setText(str(error))
        self._append_detail(f"ERROR      {error}")
        self.details_toggle.setChecked(True)
        if isinstance(error, pipeline.CandidateReviewRequired):
            self._open_candidate_review(error.result)
            return
        QMessageBox.critical(self, "Subtitle Preparation Failed", str(error))

    def _set_busy(self, busy: bool) -> None:
        self.primary_button.setEnabled(not busy and bool(self.video_path))
        self.primary_button.setText("Working..." if busy else "Prepare Subtitles")
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setValue(2)
            self.status_label.setStyleSheet(f"color: {TEXT};")

    def _open_candidate_review(
        self,
        initial_result: open_subtitles.SubtitleSearchResult | None = None,
    ) -> None:
        if not self.video_path:
            QMessageBox.information(self, "Choose Media", "Choose a media file first.")
            return
        try:
            key = self.secret_store.get(settings.OPEN_SUBTITLES_SECRET)
        except settings.SecretStorageError as exc:
            QMessageBox.critical(self, "Keychain Error", str(exc))
            return
        if not key:
            QMessageBox.information(
                self,
                "OpenSubtitles Key Required",
                "Add an OpenSubtitles API key in Settings.",
            )
            self.tabs.setCurrentIndex(2)
            return
        self._candidate_dialog = CandidateDialog(
            self,
            api_key=key,
            video_path=self.video_path,
            target_language=self.target_combo.currentData(),
            initial_result=initial_result,
        )
        self._candidate_dialog.candidate_chosen.connect(
            self._candidate_selected
        )
        self._candidate_dialog.exec()

    def _candidate_selected(
        self,
        candidate: open_subtitles.SubtitleCandidate,
    ) -> None:
        self.selected_candidate = candidate
        self.selected_subtitle_path = ""
        name = candidate.release_name or candidate.file_name
        self.sidecar_label.setText(f"Target subtitle: {name}")

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
            subprocess.run(["open", "-R", path], check=False)

    def _launch_mpv(self, path: str) -> None:
        try:
            media_launcher.launch_in_mpv(
                path,
                configured_path=self.preferences.get("mpv_path", ""),
            )
        except media_launcher.MpvLaunchError as exc:
            answer = QMessageBox.warning(
                self,
                "mpv Not Available",
                f"{exc}\n\nOpen setup instructions?",
                QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                MpvSetupDialog(self).exec()

    def _refresh_recent(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        roots = list(self.preferences["media_locations"])
        self.recent_list.clear()
        self.recent_list.addItem("Scanning approved media folders...")
        self._worker = FunctionThread(
            lambda: media_launcher.recent_media_files(roots, limit=40)
        )
        self._worker.completed.connect(self._recent_ready)
        self._worker.failed.connect(
            lambda error: self.recent_list.addItem(str(error))
        )
        self._worker.start()

    def _recent_ready(self, paths: list[Path]) -> None:
        self.recent_list.clear()
        if not paths:
            self.recent_list.addItem("No media found in approved folders")
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
            if self.os_key.text().strip():
                self.secret_store.set(
                    settings.OPEN_SUBTITLES_SECRET,
                    self.os_key.text(),
                )
        except settings.SecretStorageError as exc:
            QMessageBox.critical(self, "Keychain Error", str(exc))
            return
        self.openai_key.clear()
        self.os_key.clear()
        self._update_key_states()
        QMessageBox.information(
            self,
            "Keys Saved",
            "Credentials were saved to macOS Keychain.",
        )

    def _forget_keys(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Forget API Keys",
            "Remove both API keys from macOS Keychain?",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.secret_store.delete(settings.OPENAI_SECRET)
            self.secret_store.delete(settings.OPEN_SUBTITLES_SECRET)
        except settings.SecretStorageError as exc:
            QMessageBox.critical(self, "Keychain Error", str(exc))
            return
        self._update_key_states()

    def _update_key_states(self) -> None:
        if os.environ.get("SUBTITLE_TRANSLATOR_SMOKE_TEST") == "1":
            self.openai_state.setText("Not checked")
            self.os_state.setText("Not checked")
            self.openai_state.setStyleSheet(f"color: {MUTED};")
            self.os_state.setStyleSheet(f"color: {MUTED};")
            return
        try:
            openai_present = bool(self.secret_store.get(settings.OPENAI_SECRET))
            os_present = bool(
                self.secret_store.get(settings.OPEN_SUBTITLES_SECRET)
            )
        except settings.SecretStorageError:
            openai_present = os_present = False
        self.openai_state.setText(
            "Stored in Keychain" if openai_present else "Not configured"
        )
        self.os_state.setText(
            "Stored in Keychain" if os_present else "Not configured"
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
                QMessageBox.critical(self, "Keychain Error", str(exc))
                return
        model = self.model_combo.currentText().strip()
        self.openai_state.setText("Testing...")
        self._worker = FunctionThread(lambda: translator.test_api_key(key, model))
        self._worker.completed.connect(
            lambda _result: self._connection_test_ready(
                self.openai_state,
                "OpenAI connection ready",
            )
        )
        self._worker.failed.connect(
            lambda error: self._connection_test_failed(self.openai_state, error)
        )
        self._worker.start()

    def _test_opensubtitles(self) -> None:
        key = self.os_key.text().strip()
        if not key:
            try:
                key = self.secret_store.get(settings.OPEN_SUBTITLES_SECRET)
            except settings.SecretStorageError as exc:
                QMessageBox.critical(self, "Keychain Error", str(exc))
                return
        self.os_state.setText("Testing...")
        self._worker = FunctionThread(lambda: open_subtitles.test_api_key(key))
        self._worker.completed.connect(
            lambda _result: self._connection_test_ready(
                self.os_state,
                "OpenSubtitles connection ready",
            )
        )
        self._worker.failed.connect(
            lambda error: self._connection_test_failed(self.os_state, error)
        )
        self._worker.start()

    @staticmethod
    def _connection_test_ready(label: QLabel, text: str) -> None:
        label.setText(text)
        label.setStyleSheet(f"color: {SUCCESS};")

    @staticmethod
    def _connection_test_failed(label: QLabel, error: Exception) -> None:
        label.setText(str(error))
        label.setStyleSheet(f"color: {DANGER};")

    def _add_media_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Add Media Folder",
            str(Path.home() / "Downloads"),
        )
        if not directory:
            return
        self.preferences = self.settings_store.remember_media_location(directory)
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
            "Choose Working Folder",
            self.workspace_edit.text() or str(settings.WORKSPACE_DIR),
        )
        if directory:
            self.workspace_edit.setText(directory)

    def _open_workspace(self) -> None:
        path = Path(self.workspace_edit.text()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(path)], check=False)

    def _choose_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Choose Output Folder",
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
            "Choose mpv Executable",
            "/Applications",
            "All Files (*)",
        )
        if path:
            self.mpv_path_edit.setText(path)

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
            QMessageBox.warning(self, "Prompt Needs Attention", message)
            return
        default = languages.default_prompt_template(code).strip()
        overrides = dict(self.preferences["prompt_overrides"])
        if prompt.strip() == default:
            overrides.pop(code, None)
        else:
            overrides[code] = prompt
        self.preferences["prompt_overrides"] = overrides
        self.settings_store.save(self.preferences)
        QMessageBox.information(self, "Prompt Saved", "Language prompt updated.")

    def _save_preferences(self, *, silent: bool = False) -> None:
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
                "reasoning_effort": self.reasoning_combo.currentText(),
                "cleanup_intermediates": self.clean_checkbox.isChecked(),
                "mpv_path": self.mpv_path_edit.text().strip(),
            }
        )
        self.settings_store.save(self.preferences)
        settings.ensure_private_directories(
            self.preferences["workspace_directory"]
        )
        if not silent:
            QMessageBox.information(self, "Settings Saved", "Preferences updated.")

    def _update_dependency_status(self) -> None:
        statuses = dependencies.dependency_status()
        parts = [
            f"{item.name}: {'ready' if item.available else 'missing'}"
            for item in statuses
        ]
        required_ready = all(
            item.available for item in statuses if item.required
        )
        self.dependency_label.setText("  |  ".join(parts))
        self.dependency_label.setStyleSheet(
            f"color: {SUCCESS if required_ready else WARM};"
        )

    def _migrate_legacy_credentials(self) -> None:
        try:
            migrated = settings.migrate_legacy_credentials(self.secret_store)
        except settings.SecretStorageError as exc:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(self, "Credential Migration", str(exc)),
            )
            return
        if migrated:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.information(
                    self,
                    "Credentials Secured",
                    "Existing API keys were moved into macOS Keychain.",
                ),
            )

    def _show_first_run(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Welcome to SubtitleTranslator")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("Private local setup")
        dialog.setInformativeText(
            "Add your API keys to macOS Keychain, choose any media folder, "
            "and confirm the local media tools. The app has no account, "
            "telemetry, or developer-operated server."
        )
        settings_button = dialog.addButton(
            "Open Settings",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() == settings_button:
            self.tabs.setCurrentIndex(2)

    def _show_privacy(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Privacy")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("No developer data collection")
        dialog.setInformativeText(
            "API keys stay in macOS Keychain. Subtitle processing and media "
            "files stay on this Mac. OpenAI receives subtitle text only when "
            "you translate; OpenSubtitles receives search metadata only when "
            "you search. Requests go directly to those providers."
        )
        docs = dialog.addButton("Privacy Document", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        if dialog.clickedButton() == docs:
            QDesktopServices.openUrl(QUrl(PRIVACY_URL))


def _set_combo_data(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
