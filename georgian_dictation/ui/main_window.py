from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QCloseEvent, QIcon, QPainter, QPen, QPixmap, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QKeySequenceEdit,
)

from georgian_dictation.asr.runtime import CREATE_NO_WINDOW
from georgian_dictation.ai.gemini_client import (
    SUPPORTED_VERTEX_MODELS,
    VERTEX_LOCATION,
    VERTEX_PROJECT_ENV,
)
from georgian_dictation.audio.capture import list_input_devices
from georgian_dictation.config.credentials import CredentialError
from georgian_dictation.config.settings import SettingsStore, log_dir
from georgian_dictation.controller import ApplicationController
from georgian_dictation.models.installer import ModelInstaller, recycle_file
from georgian_dictation.models.registry import ModelRegistry, ModelSpec
from georgian_dictation.services.diagnostics import DiagnosticsRunner
from georgian_dictation.services.deepgram_tasks import DeepgramConnectionTest
from georgian_dictation.services.gemini_tasks import (
    GeminiConnectionTest,
    GeminiModelLoader,
    VertexADCCheck,
)
from georgian_dictation.services.startup import set_startup, startup_enabled
from georgian_dictation.ui.style import APP_STYLE


def card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    if title:
        label = QLabel(title)
        label.setObjectName("CardTitle")
        layout.addWidget(label)
    return frame, layout


def page_shell(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(28, 24, 28, 24)
    outer.setSpacing(14)
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    sub = QLabel(subtitle)
    sub.setObjectName("PageSubtitle")
    sub.setWordWrap(True)
    outer.addWidget(heading)
    outer.addWidget(sub)
    return page, outer


class MainWindow(QMainWindow):
    PAGE_NAMES = ["მთავარი", "მოდელები", "აუდიო", "Hotkey", "კარნახი", "AI", "Diagnostics", "Advanced"]
    AI_MODES = (
        ("Plain / Off · RAW ტექსტი", "off"),
        ("Smart Correction", "smart_correction"),
        ("AI Command", "ai_command"),
    )

    def __init__(
        self,
        settings: SettingsStore,
        registry: ModelRegistry,
        controller: ApplicationController,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.registry = registry
        self.controller = controller
        self.log = logging.getLogger(__name__)
        self.installer = ModelInstaller()
        self.diagnostics = DiagnosticsRunner()
        self._quitting = False
        self._model_process: QProcess | None = None
        self._deepgram_test: DeepgramConnectionTest | None = None
        self._gemini_test: GeminiConnectionTest | None = None
        self._gemini_loader: GeminiModelLoader | None = None
        self._vertex_adc_check: VertexADCCheck | None = None
        self.setWindowTitle("ქართული კარნახი")
        self.setMinimumSize(940, 650)
        self.resize(1080, 720)
        self.setWindowIcon(app_icon())
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._build_tray()
        self._connect_services()
        self.refresh_models()
        self.refresh_audio_devices()
        self.refresh_runtime()
        QTimer.singleShot(350, self.check_vertex_adc)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        main = QHBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 22, 12, 18)
        brand = QLabel("ქართული კარნახი")
        brand.setObjectName("Brand")
        brand_sub = QLabel("NVIDIA · DEEPGRAM · GEMINI")
        brand_sub.setObjectName("BrandSub")
        side.addWidget(brand)
        side.addWidget(brand_sub)
        side.addSpacing(20)
        self.navigation = QListWidget()
        self.navigation.setObjectName("Navigation")
        self.navigation.setFocusPolicy(Qt.NoFocus)
        for name in self.PAGE_NAMES:
            QListWidgetItem(name, self.navigation)
        side.addWidget(self.navigation, 1)
        privacy = QLabel(
            "NVIDIA: აუდიო ლოკალურია\n"
            "Deepgram: აუდიო იგზავნება cloud-ში\n"
            "Gemini: მხოლოდ transcript იგზავნება"
        )
        privacy.setObjectName("Muted")
        privacy.setWordWrap(True)
        side.addWidget(privacy)
        main.addWidget(sidebar)

        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        self.pages.addWidget(self._dashboard_page())
        self.pages.addWidget(self._models_page())
        self.pages.addWidget(self._audio_page())
        self.pages.addWidget(self._hotkey_page())
        self.pages.addWidget(self._dictation_page())
        self.pages.addWidget(self._ai_page())
        self.pages.addWidget(self._diagnostics_page())
        self.pages.addWidget(self._advanced_page())
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)

    def _dashboard_page(self) -> QWidget:
        page, layout = page_shell("მთავარი", "ქართული მეტყველება გარდაიქმნება ტექსტად NVIDIA local ან Deepgram cloud engine-ით.")
        status_card, box = card("STATUS")
        row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.setStyleSheet("background: #68DB8B; border-radius: 6px")
        self.status_value = QLabel("Idle")
        self.status_value.setObjectName("StatusValue")
        self.status_detail = QLabel("მზადაა")
        self.status_detail.setObjectName("Muted")
        texts = QVBoxLayout()
        texts.addWidget(self.status_value)
        texts.addWidget(self.status_detail)
        row.addWidget(self.status_dot)
        row.addLayout(texts)
        row.addStretch()
        self.dictation_button = QPushButton("კარნახის დაწყება")
        self.dictation_button.setObjectName("Primary")
        self.dictation_button.clicked.connect(self._toggle_dictation)
        row.addWidget(self.dictation_button)
        box.addLayout(row)
        layout.addWidget(status_card)

        details, details_box = card("CURRENT SETUP")
        form = QFormLayout()
        form.setHorizontalSpacing(28)
        self.current_microphone = QLabel("—")
        self.current_model = QLabel("—")
        self.current_backend = QLabel("—")
        self.current_hotkey = QLabel("—")
        self.dashboard_ai_mode = QComboBox()
        for label, value in self.AI_MODES:
            self.dashboard_ai_mode.addItem(label, value)
        ai_mode_index = self.dashboard_ai_mode.findData(
            self.settings.get("ai", "mode", "off")
        )
        self.dashboard_ai_mode.setCurrentIndex(max(0, ai_mode_index))
        self.dashboard_ai_mode.currentIndexChanged.connect(
            lambda: self._ai_mode_changed(self.dashboard_ai_mode)
        )
        form.addRow("მიკროფონი", self.current_microphone)
        form.addRow("ASR მოდელი", self.current_model)
        form.addRow("Backend", self.current_backend)
        form.addRow("Hotkey", self.current_hotkey)
        form.addRow("AI Processing", self.dashboard_ai_mode)
        details_box.addLayout(form)
        layout.addWidget(details)

        tip, tip_box = card("როგორ გამოვიყენოთ")
        tip_text = QLabel("მოათავსეთ კურსორი ნებისმიერ ტექსტურ ველში, დააჭირეთ hotkey-ს, ილაპარაკეთ ქართულად და იმავე hotkey-ით დაასრულეთ.")
        tip_text.setWordWrap(True)
        tip_text.setObjectName("Muted")
        tip_box.addWidget(tip_text)
        layout.addWidget(tip)
        layout.addStretch()
        return page

    def _models_page(self) -> QWidget:
        page, layout = page_shell("მოდელები", "აირჩიეთ NVIDIA local ან Deepgram Nova-3 cloud engine.")
        models_card, box = card()
        self.models_table = QTableWidget(0, 6)
        self.models_table.setHorizontalHeaderLabels(["მოდელი", "ტიპი", "სტატუსი", "ზომა", "Backend", "Local path"])
        self.models_table.verticalHeader().setVisible(False)
        self.models_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.models_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.models_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.models_table.setAlternatingRowColors(True)
        self.models_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.models_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.models_table.setMinimumHeight(255)
        self.models_table.itemSelectionChanged.connect(self._update_model_buttons)
        box.addWidget(self.models_table)
        buttons = QHBoxLayout()
        self.select_model_button = QPushButton("არჩევა")
        self.install_model_button = QPushButton("ინსტალაცია")
        self.remove_model_button = QPushButton("წაშლა")
        self.remove_model_button.setObjectName("Danger")
        self.test_model_button = QPushButton("შემოწმება")
        self.select_model_button.clicked.connect(self.select_current_model)
        self.install_model_button.clicked.connect(self.install_current_model)
        self.remove_model_button.clicked.connect(self.remove_current_model)
        self.test_model_button.clicked.connect(self.test_current_model)
        for button in (self.select_model_button, self.install_model_button, self.remove_model_button, self.test_model_button):
            buttons.addWidget(button)
        buttons.addStretch()
        box.addLayout(buttons)
        self.install_progress = QProgressBar()
        self.install_progress.setVisible(False)
        self.install_progress_label = QLabel("")
        self.install_progress_label.setObjectName("Muted")
        self.install_progress_label.setVisible(False)
        box.addWidget(self.install_progress)
        box.addWidget(self.install_progress_label)
        layout.addWidget(models_card)

        metrics, metrics_box = card("ACCURACY PRIORITY")
        ref = QLabel("Deepgram Nova-3: High Accuracy · Cloud    |    NVIDIA Accurate: Common Voice 5.73 · FLEURS 13.44    |    NVIDIA Streaming: Common Voice 7.44 · FLEURS 16.00")
        ref.setObjectName("Muted")
        ref.setWordWrap(True)
        metrics_box.addWidget(ref)
        layout.addWidget(metrics)
        layout.addStretch()
        return page

    def _audio_page(self) -> QWidget:
        page, layout = page_shell("აუდიო", "Windows input device, რეალური input level და ფრაზის დაყოფა.")
        audio_card, box = card("MICROPHONE")
        form = QFormLayout()
        self.microphone_combo = QComboBox()
        self.microphone_combo.currentIndexChanged.connect(self._save_microphone)
        form.addRow("Input device", self.microphone_combo)
        self.input_meter = QProgressBar()
        self.input_meter.setRange(0, 1000)
        self.input_meter.setValue(0)
        form.addRow("Input level", self.input_meter)
        self.test_mic_button = QPushButton("მიკროფონის ტესტი (4 წამი)")
        self.test_mic_button.clicked.connect(self.test_microphone)
        form.addRow("", self.test_mic_button)
        box.addLayout(form)
        layout.addWidget(audio_card)

        vad_card, vad_box = card("PHRASE SEGMENTATION")
        vad_form = QFormLayout()
        self.silence_combo = QComboBox()
        for label, value in (("Short · 800 ms", 800), ("Normal · 1200 ms", 1200), ("Long · 1800 ms", 1800), ("Extra long · 2500 ms", 2500)):
            self.silence_combo.addItem(label, value)
        silence = int(self.settings.get("audio", "silence_ms", 1200))
        idx = self.silence_combo.findData(silence)
        self.silence_combo.setCurrentIndex(max(0, idx))
        self.silence_combo.currentIndexChanged.connect(lambda: self.settings.set("audio", "silence_ms", self.silence_combo.currentData()))
        vad_form.addRow("End phrase after silence", self.silence_combo)
        threshold_row = QHBoxLayout()
        self.vad_slider = QSlider(Qt.Horizontal)
        self.vad_slider.setRange(3, 40)
        self.vad_slider.setValue(round(float(self.settings.get("audio", "vad_threshold", 0.012)) * 1000))
        self.vad_value = QLabel(f"{self.vad_slider.value() / 1000:.3f}")
        self.vad_slider.valueChanged.connect(self._vad_changed)
        threshold_row.addWidget(self.vad_slider)
        threshold_row.addWidget(self.vad_value)
        vad_form.addRow("Voice threshold", threshold_row)
        vad_box.addLayout(vad_form)
        layout.addWidget(vad_card)
        layout.addStretch()
        return page

    def _hotkey_page(self) -> QWidget:
        page, layout = page_shell("Hotkey", "Global activation მუშაობს მაშინაც, როცა აპის ფანჯარა დამალულია.")
        hotkey_card, box = card("ACTIVATION")
        form = QFormLayout()
        self.hotkey_edit = QKeySequenceEdit(QKeySequence(self.settings.get("hotkey", "sequence", "F8")))
        self.hotkey_edit.setMaximumSequenceLength(1)
        form.addRow("Shortcut", self.hotkey_edit)
        self.hotkey_mode = QComboBox()
        self.hotkey_mode.addItem("Toggle · ერთხელ დაწყება, მეორედ გაჩერება", "toggle")
        self.hotkey_mode.addItem("Push-to-talk · დაჭერა/გაშვება", "push_to_talk")
        mode_index = self.hotkey_mode.findData(self.settings.get("hotkey", "mode", "toggle"))
        self.hotkey_mode.setCurrentIndex(max(0, mode_index))
        form.addRow("Interaction", self.hotkey_mode)
        apply_button = QPushButton("Hotkey-ის გამოყენება")
        apply_button.setObjectName("Primary")
        apply_button.clicked.connect(self.apply_hotkey)
        form.addRow("", apply_button)
        self.hotkey_feedback = QLabel("ვამოწმებ…")
        self.hotkey_feedback.setObjectName("Muted")
        form.addRow("Status", self.hotkey_feedback)
        box.addLayout(form)
        layout.addWidget(hotkey_card)
        note, note_box = card("რჩევა")
        note_text = QLabel("F8 ან F9 ჩვეულებრივ ყველაზე ნაკლებად კონფლიქტურია. დაკავებული shortcut არ შეინახება და წინა მოქმედი hotkey აღდგება.")
        note_text.setObjectName("Muted")
        note_text.setWordWrap(True)
        note_box.addWidget(note_text)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _dictation_page(self) -> QWidget:
        page, layout = page_shell("კარნახი", "ტექსტის ჩასმა და გრძელი კარნახის ქცევა.")
        behavior, box = card("TEXT & SESSION")
        self.trailing_space = QCheckBox("Final ტექსტს ავტომატურად დაემატოს space")
        self.trailing_space.setChecked(self.settings.get("dictation", "trailing_space", True))
        self.trailing_space.toggled.connect(lambda value: self.settings.set("dictation", "trailing_space", value))
        self.punctuation = QCheckBox("მოდელის punctuation შევინარჩუნოთ")
        self.punctuation.setChecked(self.settings.get("dictation", "automatic_punctuation", True))
        self.punctuation.toggled.connect(lambda value: self.settings.set("dictation", "automatic_punctuation", value))
        self.long_dictation = QCheckBox("Long dictation · ფრაზები თანმიმდევრულად ჩაიწეროს")
        self.long_dictation.setChecked(self.settings.get("dictation", "long_dictation", True))
        self.long_dictation.toggled.connect(lambda value: self.settings.set("dictation", "long_dictation", value))
        for widget in (self.trailing_space, self.punctuation, self.long_dictation):
            box.addWidget(widget)
        insert_form = QFormLayout()
        self.insertion_combo = QComboBox()
        self.insertion_combo.addItem("Auto · Unicode, შემდეგ clipboard fallback", "auto")
        self.insertion_combo.addItem("Unicode SendInput", "unicode")
        self.insertion_combo.addItem("Clipboard fallback", "clipboard")
        insert_idx = self.insertion_combo.findData(self.settings.get("dictation", "insertion_method", "auto"))
        self.insertion_combo.setCurrentIndex(max(0, insert_idx))
        self.insertion_combo.currentIndexChanged.connect(lambda: self.settings.set("dictation", "insertion_method", self.insertion_combo.currentData()))
        insert_form.addRow("Text insertion", self.insertion_combo)
        box.addLayout(insert_form)
        layout.addWidget(behavior)
        layout.addStretch()
        return page

    def _ai_page(self) -> QWidget:
        page, layout = page_shell(
            "AI",
            "NVIDIA + AI Off = 100% Local. Deepgram-ის არჩევისას აუდიო იგზავნება Deepgram-ში; Vertex AI-ში მხოლოდ დასრულებული transcript იგზავნება — აუდიო არასოდეს.",
        )
        mode_card, mode_box = card("POST-PROCESSING")
        mode_form = QFormLayout()
        self.ai_mode_combo = QComboBox()
        for label, value in self.AI_MODES:
            self.ai_mode_combo.addItem(label, value)
        mode_index = self.ai_mode_combo.findData(self.settings.get("ai", "mode", "off"))
        self.ai_mode_combo.setCurrentIndex(max(0, mode_index))
        self.ai_mode_combo.currentIndexChanged.connect(
            lambda: self._ai_mode_changed(self.ai_mode_combo)
        )
        mode_form.addRow("Mode", self.ai_mode_combo)

        self.gemini_model_combo = QComboBox()
        saved_model = self.settings.get("ai", "gemini_model", "")
        for model in SUPPORTED_VERTEX_MODELS:
            self.gemini_model_combo.addItem(
                f"{model.display_name} ({model.id})", model.id
            )
        saved_index = self.gemini_model_combo.findData(saved_model)
        self.gemini_model_combo.setCurrentIndex(max(0, saved_index))
        self.gemini_model_combo.currentIndexChanged.connect(self._gemini_model_changed)
        if not saved_model and self.gemini_model_combo.currentData():
            self.settings.set(
                "ai", "gemini_model", self.gemini_model_combo.currentData()
            )
        model_row = QHBoxLayout()
        model_row.addWidget(self.gemini_model_combo, 1)
        self.gemini_refresh_button = QPushButton("მოდელების განახლება")
        self.gemini_refresh_button.clicked.connect(self.load_gemini_models)
        model_row.addWidget(self.gemini_refresh_button)
        mode_form.addRow("Gemini model", model_row)

        self.ai_timeout = QSpinBox()
        self.ai_timeout.setRange(5, 120)
        self.ai_timeout.setSuffix(" s")
        self.ai_timeout.setValue(int(self.settings.get("ai", "timeout_seconds", 20)))
        self.ai_timeout.valueChanged.connect(
            lambda value: self.settings.set("ai", "timeout_seconds", value)
        )
        mode_form.addRow("Timeout", self.ai_timeout)

        self.ai_aggressiveness = QComboBox()
        self.ai_aggressiveness.addItem("Conservative · მხოლოდ უდავო შეცდომები", "conservative")
        self.ai_aggressiveness.addItem("Balanced · punctuation და მკაფიო შეცდომები", "balanced")
        self.ai_aggressiveness.addItem("Strong · გრამატიკა და წაკითხვადობა", "strong")
        aggression = self.ai_aggressiveness.findData(
            self.settings.get("ai", "aggressiveness", "conservative")
        )
        self.ai_aggressiveness.setCurrentIndex(max(0, aggression))
        self.ai_aggressiveness.currentIndexChanged.connect(
            lambda: self.settings.set(
                "ai", "aggressiveness", self.ai_aggressiveness.currentData()
            )
        )
        mode_form.addRow("Correction", self.ai_aggressiveness)

        self.ai_failure_action = QComboBox()
        self.ai_failure_action.addItem("RAW ტექსტის ჩასმა (რეკომენდებული)", "insert_raw")
        self.ai_failure_action.addItem("Error-ის ჩვენება · RAW-ის შენარჩუნება", "show_error_keep")
        self.ai_failure_action.addItem("RAW-ის clipboard-ში კოპირება", "copy_raw")
        failure = self.ai_failure_action.findData(
            self.settings.get("ai", "failure_action", "insert_raw")
        )
        self.ai_failure_action.setCurrentIndex(max(0, failure))
        self.ai_failure_action.currentIndexChanged.connect(
            lambda: self.settings.set(
                "ai", "failure_action", self.ai_failure_action.currentData()
            )
        )
        mode_form.addRow("AI failure", self.ai_failure_action)
        mode_box.addLayout(mode_form)
        layout.addWidget(mode_card)

        credential, credential_box = card("GOOGLE GEMINI · VERTEX AI")
        auth_form = QFormLayout()
        auth_form.addRow("Provider", QLabel("Google Gemini / Vertex AI"))
        auth_form.addRow("Authentication", QLabel("Application Default Credentials (ADC)"))
        self.vertex_project_label = QLabel(
            os.getenv(VERTEX_PROJECT_ENV, "").strip() or "Auto-detect from ADC"
        )
        self.vertex_project_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        auth_form.addRow("Project", self.vertex_project_label)
        auth_form.addRow("Location", QLabel(VERTEX_LOCATION))
        self.vertex_status_label = QLabel("ვამოწმებ ADC ავტორიზაციას…")
        self.vertex_status_label.setObjectName("Muted")
        self.vertex_status_label.setWordWrap(True)
        auth_form.addRow("Status", self.vertex_status_label)
        credential_box.addLayout(auth_form)
        adc_note = QLabel(
            "Credential file-ის path აპში არ ინახება და ხელით არ იკითხება. თუ ADC ვერ მოიძებნა, გაუშვით: gcloud auth application-default login. თუ project ავტომატურად ვერ განისაზღვრა, დააყენეთ GEORGIAN_DICTATION_VERTEX_PROJECT."
        )
        adc_note.setObjectName("Muted")
        adc_note.setWordWrap(True)
        adc_note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        credential_box.addWidget(adc_note)
        auth_actions = QHBoxLayout()
        self.gemini_test_button = QPushButton("კავშირის შემოწმება")
        self.gemini_test_button.clicked.connect(self.test_gemini_connection)
        auth_actions.addWidget(self.gemini_test_button)
        auth_actions.addStretch()
        credential_box.addLayout(auth_actions)
        layout.addWidget(credential)
        layout.addStretch()
        return page

    def _diagnostics_page(self) -> QWidget:
        page, layout = page_shell(
            "Diagnostics / A-B ტესტი",
            "ერთი WAV შეადარეთ NVIDIA Streaming 80 ms, NVIDIA Accurate BF16 და Deepgram Nova-3-ზე; ცალკე ჩანს RAW და AI შედეგი.",
        )
        controls, box = card("TEST AUDIO")
        path_row = QHBoxLayout()
        self.wav_path = QLineEdit()
        self.wav_path.setPlaceholderText("აირჩიეთ mono/stereo PCM 16-bit WAV…")
        browse = QPushButton("არჩევა…")
        browse.clicked.connect(self.browse_wav)
        path_row.addWidget(self.wav_path, 1)
        path_row.addWidget(browse)
        box.addLayout(path_row)
        self.reference_text = QPlainTextEdit()
        self.reference_text.setPlaceholderText("სურვილისამებრ ჩაწერეთ reference transcript WER-ისთვის…")
        self.reference_text.setMaximumHeight(72)
        box.addWidget(self.reference_text)
        actions = QHBoxLayout()
        self.run_selected_diag = QPushButton("არჩეული მოდელი")
        self.run_all_diag = QPushButton("ყველა მოდელის შედარება")
        self.run_all_diag.setObjectName("Primary")
        self.run_selected_diag.clicked.connect(lambda: self.run_diagnostics(False))
        self.run_all_diag.clicked.connect(lambda: self.run_diagnostics(True))
        actions.addWidget(self.run_selected_diag)
        actions.addWidget(self.run_all_diag)
        actions.addStretch()
        box.addLayout(actions)
        layout.addWidget(controls)
        results, results_box = card("RESULTS")
        self.diag_table = QTableWidget(0, 9)
        self.diag_table.setHorizontalHeaderLabels(
            [
                "STT მოდელი",
                "RAW transcript",
                "Processed text",
                "STT დრო",
                "RTF",
                "WER",
                "AI latency",
                "Gemini model",
                "Status / fallback",
            ]
        )
        self.diag_table.verticalHeader().setVisible(False)
        self.diag_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diag_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.diag_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.diag_table.setMinimumHeight(210)
        results_box.addWidget(self.diag_table)
        layout.addWidget(results)
        layout.addStretch()
        return page

    def _advanced_page(self) -> QWidget:
        page, layout = page_shell("Advanced", "Runtime backend, დოკუმენტირებული streaming context და ლოგები.")
        runtime, box = card("RUNTIME")
        form = QFormLayout()
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("CUDA · NVIDIA GPU", "cuda")
        self.backend_combo.addItem("CPU", "cpu")
        backend_idx = self.backend_combo.findData(self.settings.get("advanced", "backend", "cuda"))
        self.backend_combo.setCurrentIndex(max(0, backend_idx))
        self.backend_combo.currentIndexChanged.connect(self._backend_changed)
        form.addRow("Backend", self.backend_combo)
        self.streaming_profile = QComboBox()
        self.streaming_profile.addItem("Fastest · RNNT right context = 1", "fastest")
        self.streaming_profile.addItem("Higher accuracy · model maximum", "higher_accuracy")
        profile_idx = self.streaming_profile.findData(self.settings.get("advanced", "streaming_profile", "fastest"))
        self.streaming_profile.setCurrentIndex(max(0, profile_idx))
        self.streaming_profile.currentIndexChanged.connect(lambda: self.settings.set("advanced", "streaming_profile", self.streaming_profile.currentData()))
        form.addRow("Streaming profile", self.streaming_profile)
        self.runtime_path = QLineEdit(self.settings.get("advanced", "nemo_runtime_dir", ""))
        self.runtime_path.setPlaceholderText("Auto-detect (რეკომენდებული)")
        runtime_row = QHBoxLayout()
        runtime_row.addWidget(self.runtime_path)
        runtime_apply = QPushButton("შემოწმება")
        runtime_apply.clicked.connect(self.apply_runtime_path)
        runtime_row.addWidget(runtime_apply)
        form.addRow("NeMo runtime", runtime_row)
        self.runtime_status_label = QLabel("—")
        self.runtime_status_label.setObjectName("Muted")
        self.runtime_status_label.setWordWrap(True)
        form.addRow("Health", self.runtime_status_label)
        log_path = QLabel(str(log_dir() / "georgian-dictation.log"))
        log_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        log_path.setObjectName("Muted")
        form.addRow("Log", log_path)
        box.addLayout(form)
        layout.addWidget(runtime)

        deepgram, deepgram_box = card("DEEPGRAM NOVA-3 · SECURE CREDENTIAL")
        deepgram_note = QLabel(
            "API key ინახება მხოლოდ Windows Credential Manager-ში. Deepgram engine-ის არჩევისას მიკროფონის აუდიო იგზავნება Deepgram Cloud-ში; NVIDIA engine-ები სრულად ლოკალური რჩება."
        )
        deepgram_note.setObjectName("Muted")
        deepgram_note.setWordWrap(True)
        deepgram_box.addWidget(deepgram_note)
        key_row = QHBoxLayout()
        self.deepgram_key = QLineEdit()
        self.deepgram_key.setEchoMode(QLineEdit.Password)
        self.deepgram_key.setPlaceholderText("ჩასვით Deepgram API key…")
        self.deepgram_show = QCheckBox("ჩვენება")
        self.deepgram_show.toggled.connect(
            lambda visible: self.deepgram_key.setEchoMode(
                QLineEdit.Normal if visible else QLineEdit.Password
            )
        )
        key_row.addWidget(self.deepgram_key, 1)
        key_row.addWidget(self.deepgram_show)
        deepgram_box.addLayout(key_row)
        key_actions = QHBoxLayout()
        self.deepgram_save_button = QPushButton("შენახვა")
        self.deepgram_remove_button = QPushButton("წაშლა")
        self.deepgram_remove_button.setObjectName("Danger")
        self.deepgram_test_button = QPushButton("კავშირის შემოწმება")
        self.deepgram_save_button.clicked.connect(self.save_deepgram_key)
        self.deepgram_remove_button.clicked.connect(self.remove_deepgram_key)
        self.deepgram_test_button.clicked.connect(self.test_deepgram_connection)
        key_actions.addWidget(self.deepgram_save_button)
        key_actions.addWidget(self.deepgram_remove_button)
        key_actions.addWidget(self.deepgram_test_button)
        key_actions.addStretch()
        deepgram_box.addLayout(key_actions)
        self.deepgram_key_status = QLabel("")
        self.deepgram_key_status.setObjectName("Muted")
        deepgram_box.addWidget(self.deepgram_key_status)
        layout.addWidget(deepgram)
        self.refresh_deepgram_credentials()

        general, gen_box = card("WINDOWS")
        self.startup_check = QCheckBox("Windows-ში შესვლისას ავტომატურად გაეშვას")
        self.startup_check.setChecked(startup_enabled())
        self.startup_check.toggled.connect(self._startup_toggled)
        self.minimize_check = QCheckBox("X ღილაკზე system tray-ში დაიმალოს")
        self.minimize_check.setChecked(self.settings.get("general", "minimize_to_tray", True))
        self.minimize_check.toggled.connect(lambda value: self.settings.set("general", "minimize_to_tray", value))
        gen_box.addWidget(self.startup_check)
        gen_box.addWidget(self.minimize_check)
        layout.addWidget(general)
        layout.addStretch()
        return page

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("ქართული კარნახი")
        menu = QMenu()
        self.tray_toggle = QAction("კარნახის დაწყება", self)
        self.tray_toggle.triggered.connect(self._toggle_dictation)
        menu.addAction(self.tray_toggle)
        menu.addSeparator()
        self.tray_models = menu.addMenu("მოდელი")
        group = QActionGroup(self)
        group.setExclusive(True)
        for model in self.registry.all():
            action = QAction(model.short_name, self, checkable=True)
            action.setData(model.id)
            action.setChecked(self.registry.selected().id == model.id)
            action.setEnabled(self.registry.is_installed(model))
            action.triggered.connect(lambda _checked=False, model_id=model.id: self._select_model(model_id))
            group.addAction(action)
            self.tray_models.addAction(action)
        menu.addSeparator()
        open_action = QAction("გახსნა", self)
        open_action.triggered.connect(self.show_normal)
        menu.addAction(open_action)
        settings_action = QAction("პარამეტრები", self)
        settings_action.triggered.connect(lambda: self.show_page(3))
        menu.addAction(settings_action)
        menu.addSeparator()
        exit_action = QAction("გასვლა", self)
        exit_action.triggered.connect(self.quit_application)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _connect_services(self) -> None:
        self.controller.status_changed.connect(self.set_status)
        self.controller.active_changed.connect(self._active_changed)
        self.controller.error.connect(self.show_error)
        self.controller.credentials_required.connect(self._show_deepgram_credentials)
        self.controller.hotkey_status.connect(self._hotkey_status)
        self.controller.audio.level_changed.connect(lambda value: self.input_meter.setValue(round(value * 1000)))
        self.installer.progress.connect(self._install_progress)
        self.installer.completed.connect(self._install_completed)
        self.installer.failed.connect(self._install_failed)
        self.installer.running_changed.connect(self._install_running)
        self.diagnostics.model_started.connect(self._diag_started)
        self.diagnostics.result.connect(self._diag_result)
        self.diagnostics.error.connect(self._diag_error)
        self.diagnostics.finished.connect(self._diag_finished)

    def set_status(self, state: str, detail: str) -> None:
        labels = {
            "idle": "Idle",
            "listening": "Listening",
            "loading": "Loading",
            "processing": "Processing",
            "transcribing": "Transcribing",
            "ai_processing": "AI Processing",
            "typing": "Typing",
            "error": "Error",
            "success": "Done",
        }
        colors = {
            "idle": "#68DB8B",
            "listening": "#55D6BE",
            "loading": "#8CA7FF",
            "processing": "#8CA7FF",
            "transcribing": "#8CA7FF",
            "ai_processing": "#B88CFF",
            "typing": "#F5C76A",
            "error": "#FF6B78",
            "success": "#68DB8B",
        }
        self.status_value.setText(labels.get(state, state.title()))
        self.status_detail.setText(detail)
        self.status_dot.setStyleSheet(f"background: {colors.get(state, '#8993A1')}; border-radius: 6px")

    def _toggle_dictation(self) -> None:
        if self.controller.active:
            self.controller.stop_dictation()
        else:
            self.controller.start_dictation()

    def _active_changed(self, active: bool) -> None:
        label = "კარნახის გაჩერება" if active else "კარნახის დაწყება"
        self.dictation_button.setText(label)
        self.tray_toggle.setText(label)

    def refresh_models(self) -> None:
        current_id = self.registry.selected().id
        self.models_table.setRowCount(0)
        for spec in self.registry.all():
            row = self.models_table.rowCount()
            self.models_table.insertRow(row)
            installed = self.registry.is_installed(spec)
            if spec.kind == "cloud":
                status = "Ready · API key saved" if installed else "API key required"
                model_type = "Cloud"
                size = "Cloud"
                backend = "Deepgram Cloud"
            else:
                status = "Installed" if installed else "Not installed"
                model_type = "Streaming" if spec.kind == "streaming" else "Accurate"
                size = f"~{spec.approx_size_mb} MB"
                backend = self.settings.get("advanced", "backend", "cuda").upper()
            if spec.id == current_id:
                status += " · Selected"
            values = [
                spec.name,
                model_type,
                status,
                size,
                backend,
                self.registry.location_for(spec),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.UserRole, spec.id)
                if col == 2:
                    item.setForeground(QColor("#68DB8B") if installed else QColor("#E6A96A"))
                self.models_table.setItem(row, col, item)
            self.models_table.setRowHeight(row, 48)
            if spec.id == current_id:
                self.models_table.selectRow(row)
        self.current_model.setText(self.registry.selected().name)
        self.current_backend.setText(
            "Deepgram Cloud"
            if self.registry.selected().kind == "cloud"
            else self.settings.get("advanced", "backend", "cuda").upper()
        )
        self._update_model_buttons()
        self._refresh_tray_models()

    def _selected_model_spec(self) -> ModelSpec:
        row = self.models_table.currentRow()
        if row < 0:
            return self.registry.selected()
        return self.registry.get(self.models_table.item(row, 0).data(Qt.UserRole))

    def _update_model_buttons(self) -> None:
        if not hasattr(self, "select_model_button"):
            return
        spec = self._selected_model_spec()
        installed = self.registry.is_installed(spec)
        busy = self.installer.running
        self.select_model_button.setEnabled(installed and spec.id != self.registry.selected().id and not busy)
        self.install_model_button.setEnabled(
            spec.kind != "cloud" and not installed and not busy
        )
        self.remove_model_button.setEnabled(
            installed
            and spec.kind == "accurate"
            and not busy
            and not self.controller.active
        )
        self.test_model_button.setEnabled(
            installed and not busy and not bool(self._deepgram_test and self._deepgram_test.isRunning())
        )

    def select_current_model(self) -> None:
        self._select_model(self._selected_model_spec().id)

    def _select_model(self, model_id: str) -> None:
        if self.controller.active:
            self.show_error("მოდელის შეცვლამდე მიმდინარე კარნახი გააჩერეთ")
            return
        if not self.registry.is_installed(model_id):
            spec = self.registry.get(model_id)
            if spec.kind == "cloud":
                self.show_error("Deepgram API key ჯერ შენახული არ არის")
                self._show_deepgram_credentials()
            else:
                self.show_error("არჩეული მოდელი ჯერ დაყენებული არ არის")
            return
        self.registry.select(model_id)
        self.refresh_models()

    def install_current_model(self) -> None:
        spec = self._selected_model_spec()
        path = self.registry.path_for(spec)
        if path is None:
            self._show_deepgram_credentials()
            return
        self.installer.install(spec, path)

    def remove_current_model(self) -> None:
        spec = self._selected_model_spec()
        if spec.kind == "streaming":
            self.show_error("არსებული მუშა streaming მოდელი დაცულია და აპიდან არ იშლება")
            return
        answer = QMessageBox.question(self, "მოდელის წაშლა", f"{spec.name}\n\nფაილი გადავიდეს Recycle Bin-ში?")
        if answer != QMessageBox.Yes:
            return
        path = self.registry.path_for(spec)
        if path is None:
            return
        if recycle_file(path):
            if self.registry.selected().id == spec.id:
                self.registry.select("georgian-streaming-80ms")
            self.refresh_models()
        else:
            self.show_error("მოდელის Recycle Bin-ში გადატანა ვერ მოხერხდა")

    def test_current_model(self) -> None:
        spec = self._selected_model_spec()
        if spec.kind == "cloud":
            self.test_deepgram_connection()
            return
        cli = self.controller.runtime_status.cli_path
        if not cli:
            self.show_error("NeMo runtime ვერ მოიძებნა")
            return
        self.test_model_button.setEnabled(False)
        process = QProcess(self)
        self._model_process = process
        process.setProgram(str(cli))
        path = self.registry.path_for(spec)
        if path is None:
            self.show_error("ლოკალური მოდელის ფაილი ვერ მოიძებნა")
            self.test_model_button.setEnabled(True)
            return
        process.setArguments(["model", "info", str(path), "--json"])
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.finished.connect(lambda code, _status: self._model_test_finished(process, code))
        process.start()

    def _model_test_finished(self, process: QProcess, code: int) -> None:
        output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.test_model_button.setEnabled(True)
        if code == 0:
            try:
                info = json.loads(output)
                QMessageBox.information(self, "მოდელის შემოწმება", f"Runtime compatible: {info.get('runtime_compatible')}\nArchitecture: {info.get('architecture')}\nTensors: {info.get('tensor_count')}\nSize: {info.get('size', 0) / 1024 / 1024:.1f} MB")
            except json.JSONDecodeError:
                QMessageBox.information(self, "მოდელის შემოწმება", output)
        else:
            self.show_error(output.strip())

    def refresh_deepgram_credentials(self) -> None:
        try:
            saved = self.registry.credentials.exists()
            self.deepgram_key_status.setText(
                "შენახულია Windows Credential Manager-ში"
                if saved
                else "API key ჯერ შენახული არ არის"
            )
            self.deepgram_key_status.setStyleSheet(
                f"color: {'#68DB8B' if saved else '#E6A96A'}"
            )
            self.deepgram_remove_button.setEnabled(saved)
            self.deepgram_test_button.setEnabled(saved or bool(self.deepgram_key.text().strip()))
        except CredentialError as exc:
            self.deepgram_key_status.setText("Error · " + str(exc))
            self.deepgram_key_status.setStyleSheet("color: #FF929C")
            self.deepgram_remove_button.setEnabled(False)
            self.deepgram_test_button.setEnabled(False)

    def _show_deepgram_credentials(self) -> None:
        self.show_page(7)
        self.deepgram_key.setFocus()

    def save_deepgram_key(self) -> None:
        if self.controller.active:
            self.show_error("API key-ის შეცვლამდე მიმდინარე კარნახი გააჩერეთ")
            return
        api_key = self.deepgram_key.text().strip()
        if not api_key:
            self.show_error("ჩასვით Deepgram API key")
            self.deepgram_key.setFocus()
            return
        try:
            self.registry.credentials.save(api_key)
        except CredentialError as exc:
            self.show_error(str(exc))
            return
        self.deepgram_key.clear()
        self.deepgram_show.setChecked(False)
        self.refresh_deepgram_credentials()
        self.refresh_models()
        self.status_detail.setText("Deepgram API key უსაფრთხოდ შეინახა Windows Credential Manager-ში")

    def remove_deepgram_key(self) -> None:
        if self.controller.active:
            self.show_error("API key-ის წაშლამდე მიმდინარე კარნახი გააჩერეთ")
            return
        answer = QMessageBox.question(
            self,
            "Deepgram API key-ის წაშლა",
            "Windows Credential Manager-იდან შენახული Deepgram API key წაიშალოს?",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.registry.credentials.remove()
        except CredentialError as exc:
            self.show_error(str(exc))
            return
        if self.registry.selected().kind == "cloud":
            self.registry.select("georgian-streaming-80ms")
        self.deepgram_key.clear()
        self.deepgram_show.setChecked(False)
        self.refresh_deepgram_credentials()
        self.refresh_models()
        self.status_detail.setText("Deepgram API key წაიშალა")

    def test_deepgram_connection(self) -> None:
        if self._deepgram_test and self._deepgram_test.isRunning():
            return
        api_key = self.deepgram_key.text().strip()
        if not api_key:
            try:
                api_key = self.registry.credentials.read() or ""
            except CredentialError as exc:
                self.show_error(str(exc))
                return
        if not api_key:
            self.show_error("Deepgram API key ჯერ შენახული არ არის")
            self._show_deepgram_credentials()
            return
        self.deepgram_test_button.setEnabled(False)
        self.test_model_button.setEnabled(False)
        self.deepgram_key_status.setText("Deepgram Nova-3 / ka კავშირს ვამოწმებ…")
        self.deepgram_key_status.setStyleSheet("color: #8CA7FF")
        worker = DeepgramConnectionTest(api_key)
        self._deepgram_test = worker
        worker.succeeded.connect(self._deepgram_test_succeeded)
        worker.failed.connect(self._deepgram_test_failed)
        worker.finished.connect(self._deepgram_test_finished)
        worker.start()

    def _deepgram_test_succeeded(self, message: str) -> None:
        self.deepgram_key_status.setText("OK · " + message)
        self.deepgram_key_status.setStyleSheet("color: #68DB8B")
        QMessageBox.information(self, "Deepgram", message)

    def _deepgram_test_failed(self, message: str) -> None:
        self.deepgram_key_status.setText("Error · " + message)
        self.deepgram_key_status.setStyleSheet("color: #FF929C")
        self.show_error(message)

    def _deepgram_test_finished(self) -> None:
        self.deepgram_test_button.setEnabled(True)
        self.test_model_button.setEnabled(True)
        self.refresh_models()

    def _ai_mode_changed(self, source: QComboBox) -> None:
        mode = source.currentData() or "off"
        previous = self.settings.get("ai", "mode", "off")
        if self.controller.active:
            self.show_error("AI რეჟიმის შეცვლამდე მიმდინარე კარნახი გააჩერეთ")
            self._sync_ai_mode(previous)
            return
        self.settings.set("ai", "mode", mode)
        self._sync_ai_mode(mode)

    def _sync_ai_mode(self, mode: str) -> None:
        for combo_name in ("dashboard_ai_mode", "ai_mode_combo"):
            combo = getattr(self, combo_name, None)
            if combo is None:
                continue
            combo.blockSignals(True)
            index = combo.findData(mode)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)

    def check_vertex_adc(self) -> None:
        if self._vertex_adc_check and self._vertex_adc_check.isRunning():
            return
        self.vertex_status_label.setText("ვამოწმებ Google ADC ავტორიზაციას…")
        self.vertex_status_label.setStyleSheet("color: #8CA7FF")
        self.gemini_test_button.setEnabled(False)
        self.gemini_refresh_button.setEnabled(False)
        worker = VertexADCCheck()
        self._vertex_adc_check = worker
        worker.succeeded.connect(self._vertex_adc_succeeded)
        worker.failed.connect(self._vertex_adc_failed)
        worker.finished.connect(self._gemini_worker_finished)
        worker.start()

    def _vertex_adc_succeeded(self, status: object) -> None:
        vertex_project = getattr(status, "vertex_project", "")
        quota_project = getattr(status, "quota_project", "") or vertex_project
        if vertex_project:
            self.vertex_project_label.setText(vertex_project)
        self.vertex_status_label.setText(
            f"✓ Google ADC authenticated · quota project: {quota_project or 'not set'}"
        )
        self.vertex_status_label.setStyleSheet("color: #68DB8B")
        self.settings.set("ai", "provider", "vertex_ai_adc")

    def _vertex_adc_failed(self, message: str) -> None:
        self.vertex_status_label.setText("Not authenticated · " + message)
        self.vertex_status_label.setStyleSheet("color: #E6A96A")
        self.status_detail.setText("Vertex AI კონფიგურაცია/ავტორიზაცია ვერ დადასტურდა — " + message)

    def _populate_gemini_models(self, models: object, selected: str = "") -> None:
        items = list(models) if models else []
        saved = selected or self.settings.get("ai", "gemini_model", "")
        self.gemini_model_combo.blockSignals(True)
        self.gemini_model_combo.clear()
        for index, item in enumerate(items):
            suffix = " · Verified" if item.id == selected else " · Default priority" if index == 0 else ""
            self.gemini_model_combo.addItem(f"{item.display_name} ({item.id}){suffix}", item.id)
        selected_index = self.gemini_model_combo.findData(saved)
        self.gemini_model_combo.setCurrentIndex(max(0, selected_index))
        self.gemini_model_combo.blockSignals(False)
        chosen = self.gemini_model_combo.currentData()
        if chosen:
            self.settings.set("ai", "gemini_model", chosen)

    def _gemini_model_changed(self) -> None:
        model = self.gemini_model_combo.currentData()
        if model:
            self.settings.set("ai", "gemini_model", model)

    def load_gemini_models(self) -> None:
        if self._gemini_loader and self._gemini_loader.isRunning():
            return
        self.vertex_status_label.setText(
            "Vertex AI-ზე default Flash მოდელს რეალური generation-ით ვამოწმებ…"
        )
        self.vertex_status_label.setStyleSheet("color: #8CA7FF")
        worker = GeminiModelLoader(self.ai_timeout.value())
        self._gemini_loader = worker
        worker.succeeded.connect(self._gemini_models_loaded)
        worker.failed.connect(self._gemini_failed)
        worker.finished.connect(self._gemini_worker_finished)
        self.gemini_test_button.setEnabled(False)
        self.gemini_refresh_button.setEnabled(False)
        worker.start()

    def _gemini_models_loaded(self, models: object, working_default: str) -> None:
        self._populate_gemini_models(models, working_default)
        self.vertex_status_label.setText(
            f"✓ ADC authenticated · working default: {working_default}"
        )
        self.vertex_status_label.setStyleSheet("color: #68DB8B")

    def test_gemini_connection(self) -> None:
        if self._gemini_test and self._gemini_test.isRunning():
            return
        self.vertex_status_label.setText("Vertex AI კავშირსა და generation-ს ვამოწმებ…")
        self.vertex_status_label.setStyleSheet("color: #8CA7FF")
        worker = GeminiConnectionTest(
            self.gemini_model_combo.currentData() or "",
            self.ai_timeout.value(),
        )
        self._gemini_test = worker
        worker.succeeded.connect(self._gemini_test_succeeded)
        worker.failed.connect(self._gemini_failed)
        worker.finished.connect(self._gemini_worker_finished)
        self.gemini_test_button.setEnabled(False)
        self.gemini_refresh_button.setEnabled(False)
        worker.start()

    def _gemini_test_succeeded(self, models: object, used_model: str) -> None:
        self._populate_gemini_models(models, used_model)
        self.vertex_status_label.setText(
            f"✓ Vertex AI connection successful · {used_model}"
        )
        self.vertex_status_label.setStyleSheet("color: #68DB8B")
        QMessageBox.information(
            self,
            "Vertex AI",
            f"ADC ავტორიზაცია და ტექსტის generation წარმატებულია.\nModel: {used_model}",
        )

    def _gemini_failed(self, message: str) -> None:
        self.vertex_status_label.setText("Error · " + message)
        self.vertex_status_label.setStyleSheet("color: #FF929C")
        self.show_error(message)

    def _gemini_worker_finished(self) -> None:
        self.gemini_test_button.setEnabled(True)
        self.gemini_refresh_button.setEnabled(True)

    def _install_running(self, running: bool) -> None:
        self.install_progress.setVisible(running)
        self.install_progress_label.setVisible(running)
        self._update_model_buttons()

    def _install_progress(self, value: int, message: str) -> None:
        self.install_progress.setRange(0, 100)
        self.install_progress.setValue(value)
        self.install_progress_label.setText(message)

    def _install_completed(self, _path: str) -> None:
        self.refresh_models()
        self.install_progress_label.setText("მოდელი მზადაა")
        QMessageBox.information(self, "მოდელი", "Accurate მოდელი წარმატებით დაყენდა და შემოწმდა.")

    def _install_failed(self, message: str) -> None:
        self.install_progress_label.setText("ინსტალაცია ვერ დასრულდა")
        self.show_error(message)

    def refresh_audio_devices(self) -> None:
        saved_id = self.settings.get("audio", "device_id")
        self.microphone_combo.blockSignals(True)
        self.microphone_combo.clear()
        try:
            devices = list_input_devices()
            for device in devices:
                self.microphone_combo.addItem(device.label, device.id)
            index = self.microphone_combo.findData(saved_id)
            self.microphone_combo.setCurrentIndex(max(0, index))
            if self.microphone_combo.count():
                self.current_microphone.setText(self.microphone_combo.currentText())
        except Exception as exc:
            self.microphone_combo.addItem(f"მიკროფონები ვერ მოიძებნა: {exc}", None)
        finally:
            self.microphone_combo.blockSignals(False)

    def _save_microphone(self) -> None:
        if self.microphone_combo.currentIndex() < 0:
            return
        self.settings.set("audio", "device_id", self.microphone_combo.currentData(), save=False)
        self.settings.set("audio", "device_name", self.microphone_combo.currentText())
        self.current_microphone.setText(self.microphone_combo.currentText())

    def test_microphone(self) -> None:
        if self.controller.active or self.controller.audio.active:
            self.show_error("მიკროფონი უკვე გამოიყენება")
            return
        self.test_mic_button.setEnabled(False)
        try:
            self.controller.audio.start(self.microphone_combo.currentData(), lambda _a, _r: None)
            QTimer.singleShot(4000, self._finish_mic_test)
        except RuntimeError:
            self.test_mic_button.setEnabled(True)

    def _finish_mic_test(self) -> None:
        self.controller.audio.stop()
        self.test_mic_button.setEnabled(True)

    def _vad_changed(self, value: int) -> None:
        threshold = value / 1000
        self.vad_value.setText(f"{threshold:.3f}")
        self.settings.set("audio", "vad_threshold", threshold)

    def apply_hotkey(self) -> None:
        sequence = self.hotkey_edit.keySequence().toString(QKeySequence.PortableText)
        self.controller.apply_hotkey(sequence, self.hotkey_mode.currentData())

    def _hotkey_status(self, ok: bool, message: str) -> None:
        self.hotkey_feedback.setText(("OK · " if ok else "Error · ") + message)
        self.hotkey_feedback.setStyleSheet(f"color: {'#68DB8B' if ok else '#FF929C'}")
        if ok:
            self.current_hotkey.setText(self.settings.get("hotkey", "sequence", "F8"))

    def browse_wav(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "WAV ფაილის არჩევა", "", "WAV audio (*.wav)")
        if path:
            self.wav_path.setText(path)

    def run_diagnostics(self, all_models: bool) -> None:
        wav = Path(self.wav_path.text().strip())
        if not wav.is_file():
            self.show_error("აირჩიეთ არსებული WAV ფაილი")
            return
        specs = self.registry.all() if all_models else [self.registry.selected()]
        models = [(spec, self.registry.path_for(spec)) for spec in specs if self.registry.is_installed(spec)]
        if not models:
            self.show_error("ტესტისთვის დაყენებული მოდელი ვერ მოიძებნა")
            return
        api_key: str | None = None
        if any(spec.kind == "cloud" for spec, _path in models):
            try:
                api_key = self.registry.credentials.read()
            except CredentialError as exc:
                self.show_error(str(exc))
                return
            if not api_key:
                self.show_error("Deepgram diagnostics-ისთვის API key საჭიროა")
                self._show_deepgram_credentials()
                return
        ai_mode = self.settings.get("ai", "mode", "off")
        self.diag_table.setRowCount(0)
        self.run_selected_diag.setEnabled(False)
        self.run_all_diag.setEnabled(False)
        self.diagnostics.run_models(
            wav,
            models,
            backend=self.settings.get("advanced", "backend", "cuda"),
            reference=self.reference_text.toPlainText(),
            runtime_dir=self.settings.get("advanced", "nemo_runtime_dir", ""),
            api_key=api_key,
            ai_mode=ai_mode,
            gemini_model=self.settings.get("ai", "gemini_model", ""),
            ai_timeout_seconds=int(self.settings.get("ai", "timeout_seconds", 20)),
            ai_aggressiveness=self.settings.get("ai", "aggressiveness", "conservative"),
            ai_failure_action=self.settings.get("ai", "failure_action", "insert_raw"),
        )

    def _diag_started(self, model_id: str) -> None:
        spec = self.registry.get(model_id)
        row = self.diag_table.rowCount()
        self.diag_table.insertRow(row)
        self.diag_table.setItem(row, 0, QTableWidgetItem(spec.short_name))
        self.diag_table.setItem(row, 1, QTableWidgetItem("მუშავდება…"))
        self.diag_table.item(row, 0).setData(Qt.UserRole, model_id)

    def _diag_row(self, model_id: str) -> int:
        for row in range(self.diag_table.rowCount()):
            if self.diag_table.item(row, 0).data(Qt.UserRole) == model_id:
                return row
        return -1

    def _diag_result(
        self,
        model_id: str,
        raw: str,
        processed: str,
        elapsed: float,
        rtf: float,
        wer: str,
        ai_latency: float,
        gemini_model: str,
        ai_status: str,
    ) -> None:
        row = self._diag_row(model_id)
        values = [
            raw or "(ცარიელი)",
            processed or "(ცარიელი)",
            f"{elapsed:.2f} s",
            f"{rtf:.3f}",
            wer,
            f"{ai_latency:.2f} s" if ai_latency else "—",
            gemini_model,
            ai_status,
        ]
        for col, value in enumerate(values, start=1):
            self.diag_table.setItem(row, col, QTableWidgetItem(value))

    def _diag_error(self, model_id: str, message: str) -> None:
        row = self._diag_row(model_id)
        self.diag_table.setItem(row, 1, QTableWidgetItem("Error: " + message))
        self.diag_table.setItem(row, 8, QTableWidgetItem("STT Error"))

    def _diag_finished(self) -> None:
        self.run_selected_diag.setEnabled(True)
        self.run_all_diag.setEnabled(True)

    def _backend_changed(self) -> None:
        backend = self.backend_combo.currentData()
        if backend == "cuda" and not self.controller.runtime_status.cuda_available:
            self.show_error("CUDA backend ხელმისაწვდომი არ არის")
            self.backend_combo.setCurrentIndex(self.backend_combo.findData("cpu"))
            return
        self.settings.set("advanced", "backend", backend)
        self.current_backend.setText(backend.upper())
        self.refresh_models()

    def apply_runtime_path(self) -> None:
        self.settings.set("advanced", "nemo_runtime_dir", self.runtime_path.text().strip())
        self.controller.runtime_status = self.controller.runtime_status.__class__(False, None, None)
        from georgian_dictation.asr.runtime import inspect_runtime
        self.controller.runtime_status = inspect_runtime(self.runtime_path.text().strip())
        self.refresh_runtime()

    def refresh_runtime(self) -> None:
        status = self.controller.runtime_status
        if status.available:
            backend = self.settings.get("advanced", "backend", "cuda").upper()
            self.runtime_status_label.setText(f"OK · NeMo-Speech.cpp {status.version} · CUDA {'available' if status.cuda_available else 'unavailable'} · {status.cli_path}")
            self.runtime_status_label.setStyleSheet("color: #68DB8B")
            self.current_backend.setText(
                "Deepgram Cloud"
                if self.registry.selected().kind == "cloud"
                else backend
            )
        else:
            self.runtime_status_label.setText("Error · " + status.message)
            self.runtime_status_label.setStyleSheet("color: #FF929C")
        self.current_hotkey.setText(self.settings.get("hotkey", "sequence", "F8"))

    def _startup_toggled(self, enabled: bool) -> None:
        try:
            set_startup(enabled)
            self.settings.set("general", "launch_at_startup", enabled)
        except OSError as exc:
            self.startup_check.blockSignals(True)
            self.startup_check.setChecked(not enabled)
            self.startup_check.blockSignals(False)
            self.show_error(f"Startup პარამეტრი ვერ შეიცვალა: {exc}")

    def _refresh_tray_models(self) -> None:
        if not hasattr(self, "tray_models"):
            return
        selected = self.registry.selected().id
        for action in self.tray_models.actions():
            model_id = action.data()
            action.setChecked(model_id == selected)
            action.setEnabled(self.registry.is_installed(model_id))

    def show_error(self, message: str) -> None:
        self.status_detail.setText(message)
        if self.tray.isVisible():
            self.tray.showMessage("ქართული კარნახი", message, QSystemTrayIcon.Warning, 5000)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_normal()

    def show_normal(self) -> None:
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_page(self, index: int) -> None:
        self.show_normal()
        self.navigation.setCurrentRow(index)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._quitting and self.settings.get("general", "minimize_to_tray", True) and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage("ქართული კარნახი", "აპი მუშაობას system tray-ში აგრძელებს.", QSystemTrayIcon.Information, 2500)
        else:
            event.accept()

    def quit_application(self) -> None:
        self._quitting = True
        self.controller.shutdown()
        self.tray.hide()
        QApplication.quit()


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#50CFB6"))
    painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
    painter.setPen(QPen(QColor("#10241F"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(27, 15, 10, 22, 5, 5)
    painter.drawArc(20, 24, 24, 21, 180 * 16, 180 * 16)
    painter.drawLine(32, 45, 32, 51)
    painter.drawLine(25, 51, 39, 51)
    painter.end()
    return QIcon(pixmap)
