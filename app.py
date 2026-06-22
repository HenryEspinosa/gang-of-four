#!/usr/bin/env python3
"""Perplexity Council -- a desktop chat GUI for Ubuntu.

A native Qt (PySide6) chat interface that talks to the Perplexity API and
replicates the "Model Council" experience: each query is answered by several
Sonar models in parallel, then a synthesizer model produces one combined answer
that highlights consensus and disagreement. Run with:  python app.py
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QFont, QKeySequence, QTextDocument, QIcon, QPixmap, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QTextBrowser, QScrollArea, QFrame, QSplitter,
    QDialog, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QDialogButtonBox, QFormLayout, QGroupBox, QToolButton, QSizePolicy,
    QMessageBox, QFileDialog,
)

import config
import store
import council
import documents
from council import (
    PerplexityClient, CouncilController, AVAILABLE_MODELS, display_name,
)

SEARCH_MODES = ["web", "academic", "sec"]


def fill_model_combo(combo, selected: str, model_ids: list):
    """Populate a combo with friendly labels but keep the raw id as data."""
    combo.clear()
    for m in model_ids:
        combo.addItem(display_name(m), m)
    idx = combo.findData(selected)
    combo.setCurrentIndex(idx if idx >= 0 else 0)

APP_TITLE = "Gang of Four"


def _resource_root() -> str:
    """Directory that holds bundled resources. When frozen by PyInstaller the
    data files are unpacked under sys._MEIPASS; otherwise it's this file's dir."""
    base = getattr(sys, "_MEIPASS", None)
    return base or os.path.dirname(os.path.abspath(__file__))


ASSETS_DIR = os.path.join(_resource_root(), "assets")


# --------------------------------------------------------------------------- #
# Reusable widgets
# --------------------------------------------------------------------------- #
class MessageView(QTextBrowser):
    """A QTextBrowser that renders markdown and sizes itself to its content."""

    def __init__(self):
        super().__init__()
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._md = ""

    def set_markdown(self, text: str):
        self._md = text
        self.setMarkdown(text)
        self._adjust()

    def refresh(self):
        """Re-lay-out and recompute height (e.g. after a font-size change)."""
        if self._md:
            self.setMarkdown(self._md)
        self._adjust()

    def _adjust(self):
        w = max(self.viewport().width(), 50)
        self.document().setTextWidth(w)
        h = self.document().size().height()
        self.setFixedHeight(int(h) + 6)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._adjust()


class MessageRow(QFrame):
    """One turn in the conversation: an author badge plus rendered content."""

    def __init__(self, author: str, kind: str):
        super().__init__()
        self.setObjectName("userRow" if kind == "user" else "aiRow")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        badge = QLabel(author)
        badge.setObjectName("authorBadge")
        f = badge.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() - 1)
        badge.setFont(f)
        lay.addWidget(badge)

        self.view = MessageView()
        lay.addWidget(self.view)

    def set_markdown(self, text: str):
        self.view.set_markdown(text)


class CollapsibleSection(QFrame):
    """A header button that expands/collapses a markdown content area."""

    def __init__(self, title: str, expanded: bool = False):
        super().__init__()
        self.setObjectName("councilCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.toggle = QToolButton()
        self.toggle.setObjectName("councilHeader")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle.clicked.connect(self._on_toggle)
        lay.addWidget(self.toggle)

        self.view = MessageView()
        self.view.setVisible(expanded)
        lay.addWidget(self.view)

    def _on_toggle(self, checked: bool):
        self.toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.view.setVisible(checked)

    def set_title(self, title: str):
        self.toggle.setText(title)

    def set_markdown(self, text: str):
        self.view.set_markdown(text)


class HistoryRow(QFrame):
    """A saved-conversation row: a checkbox (for multi-select delete) plus a
    title button that opens the conversation."""

    def __init__(self, meta: dict, on_open):
        super().__init__()
        self.setObjectName("historyRow")
        self.cid = meta["id"]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(6)

        self.check = QCheckBox()
        self.check.setToolTip("Select for deletion")
        lay.addWidget(self.check)

        title = meta.get("title") or "New chat"
        self.btn = QToolButton()
        self.btn.setObjectName("historyTitle")
        self.btn.setText(title)
        self.btn.setToolTip(f"{title}\n{meta.get('updated', '')} · "
                            f"{meta.get('count', 0)} messages")
        self.btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn.clicked.connect(lambda: on_open(self.cid))
        lay.addWidget(self.btn, 1)

    def checked(self) -> bool:
        return self.check.isChecked()

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


# --------------------------------------------------------------------------- #
# Settings dialog
# --------------------------------------------------------------------------- #
class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, model_ids: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)
        self.cfg = dict(cfg)
        self.model_ids = model_ids

        form = QFormLayout()

        self.api_key = QLineEdit(cfg.get("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("pplx-...")
        form.addRow("Perplexity API key", self.api_key)

        # Council member checkboxes (scrollable -- the catalogue is long).
        self.member_boxes: dict[str, QCheckBox] = {}
        members_group = QGroupBox("Council members (run in parallel)")
        mg = QVBoxLayout(members_group)
        inner = QWidget()
        ig = QVBoxLayout(inner)
        ig.setContentsMargins(0, 0, 0, 0)
        for m in model_ids:
            cb = QCheckBox(display_name(m))
            cb.setChecked(m in cfg.get("council_models", []))
            self.member_boxes[m] = cb
            ig.addWidget(cb)
        members_scroll = QScrollArea()
        members_scroll.setWidgetResizable(True)
        members_scroll.setWidget(inner)
        members_scroll.setFixedHeight(180)
        members_scroll.setFrameShape(QFrame.NoFrame)
        mg.addWidget(members_scroll)

        self.synth = QComboBox()
        fill_model_combo(self.synth, cfg.get("synth_model", "sonar-pro"), model_ids)
        form.addRow("Synthesizer model", self.synth)

        self.single = QComboBox()
        fill_model_combo(self.single, cfg.get("single_model", "sonar-pro"), model_ids)
        form.addRow("Single-chat model", self.single)

        self.temp = QDoubleSpinBox()
        self.temp.setRange(0.0, 2.0)
        self.temp.setSingleStep(0.1)
        self.temp.setValue(float(cfg.get("temperature", 0.2)))
        form.addRow("Temperature", self.temp)

        self.search = QComboBox()
        self.search.addItems(["web", "academic", "sec"])
        self.search.setCurrentText(cfg.get("search_mode", "web"))
        form.addRow("Search mode", self.search)

        self.font_size = QSpinBox()
        self.font_size.setRange(10, 28)
        self.font_size.setSuffix(" px")
        self.font_size.setValue(int(cfg.get("font_size", 14)))
        self.font_size.setToolTip("Size of the chat, council, and history text")
        form.addRow("Chat font size", self.font_size)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(members_group)
        root.addWidget(buttons)

    def result_config(self) -> dict:
        self.cfg["api_key"] = self.api_key.text().strip()
        self.cfg["council_models"] = [m for m, cb in self.member_boxes.items() if cb.isChecked()]
        self.cfg["synth_model"] = self.synth.currentData()
        self.cfg["single_model"] = self.single.currentData()
        self.cfg["temperature"] = self.temp.value()
        self.cfg["search_mode"] = self.search.currentText()
        self.cfg["font_size"] = self.font_size.value()
        return self.cfg


# --------------------------------------------------------------------------- #
# Input box (Ctrl+Enter to send)
# --------------------------------------------------------------------------- #
class InputBox(QPlainTextEdit):
    def __init__(self, on_send):
        super().__init__()
        self._on_send = on_send
        self.setPlaceholderText("Ask the council…  (Ctrl+Enter to send)")
        self.setFixedHeight(90)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and (e.modifiers() & Qt.ControlModifier):
            self._on_send()
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = config.load()
        self.model_ids = self._load_model_ids()
        self.current = store.Conversation.new()
        self.messages: list[dict] = self.current.messages  # API history (aliased)
        self.history_rows: list[HistoryRow] = []
        self.controller: CouncilController | None = None
        self.sections: dict[str, CollapsibleSection] = {}
        self._assist_buffer = ""
        self._assist_row: MessageRow | None = None
        self._current_question = ""
        self._running = False
        self._doc_text = ""
        self._doc_name = ""

        self.setWindowTitle(APP_TITLE)
        self.resize(1320, 780)
        self._build_ui()
        self._apply_theme()
        self._refresh_history()

        if not self.cfg.get("api_key"):
            self._add_system_note(
                "No API key set. Open **Settings** (top-right) and paste your "
                "Perplexity API key to begin."
            )

    def _load_model_ids(self) -> list:
        """The live catalogue from /v1/models, so the model list stays current.
        Falls back to the built-in list when offline or without a key."""
        key = self.cfg.get("api_key", "")
        if key:
            try:
                return council.fetch_models(key)
            except Exception:  # noqa: BLE001
                pass
        return list(AVAILABLE_MODELS)

    # ---- UI construction -------------------------------------------------- #
    def _build_ui(self):
        # Top bar
        top = QFrame()
        top.setObjectName("topBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 8, 16, 8)

        logo = QLabel()
        logo_pm = QPixmap(os.path.join(ASSETS_DIR, "icon_32.png"))
        if not logo_pm.isNull():
            logo.setPixmap(logo_pm)
            tl.addWidget(logo)

        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        tf = title.font()
        tf.setPointSize(tf.pointSize() + 2)
        tf.setBold(True)
        title.setFont(tf)
        tl.addWidget(title)
        tl.addStretch()

        self.council_toggle = QCheckBox("Council mode")
        self.council_toggle.setChecked(bool(self.cfg.get("council_enabled", True)))
        self.council_toggle.toggled.connect(self._on_council_toggle)
        tl.addWidget(self.council_toggle)

        self.single_combo = QComboBox()
        fill_model_combo(self.single_combo, self.cfg.get("single_model", "sonar-pro"),
                         self.model_ids)
        self.single_combo.setEnabled(not self.council_toggle.isChecked())
        self.single_combo.currentIndexChanged.connect(self._on_single_changed)
        tl.addWidget(self.single_combo)

        search_label = QLabel("Search:")
        search_label.setObjectName("topBarLabel")
        tl.addWidget(search_label)
        self.search_combo = QComboBox()
        self.search_combo.addItems(SEARCH_MODES)
        self.search_combo.setCurrentText(self.cfg.get("search_mode", "web"))
        self.search_combo.setToolTip(
            "Grounding source for every chat:\n"
            "• web — the general web (default)\n"
            "• academic — peer-reviewed / scholarly sources\n"
            "• sec — U.S. SEC filings (10-K, 10-Q, 8-K…)"
        )
        self.search_combo.currentTextChanged.connect(self._on_search_changed)
        tl.addWidget(self.search_combo)

        new_btn = QPushButton("New chat")
        new_btn.clicked.connect(self._new_chat)
        tl.addWidget(new_btn)

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.clicked.connect(self._open_settings)
        tl.addWidget(settings_btn)

        # History (far-left) panel
        self.history_panel = self._build_history_panel()

        # Chat (left) scroll area
        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(0)
        self.chat_layout.addStretch()
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setWidget(self.chat_container)
        self.chat_scroll.setFrameShape(QFrame.NoFrame)

        # Council (right) scroll area
        self.council_container = QWidget()
        self.council_layout = QVBoxLayout(self.council_container)
        self.council_layout.setContentsMargins(12, 12, 12, 12)
        self.council_layout.setSpacing(10)
        hdr = QLabel("Council members")
        hdr.setObjectName("panelHeader")
        self.council_layout.addWidget(hdr)
        self.council_hint = QLabel("Each member answers in parallel; the synthesizer "
                                   "combines them on the left.")
        self.council_hint.setObjectName("panelHint")
        self.council_hint.setWordWrap(True)
        self.council_layout.addWidget(self.council_hint)
        self.council_layout.addStretch()
        council_scroll = QScrollArea()
        council_scroll.setWidgetResizable(True)
        council_scroll.setWidget(self.council_container)
        council_scroll.setFrameShape(QFrame.NoFrame)
        self.council_panel = council_scroll

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.history_panel)
        self.splitter.addWidget(self.chat_scroll)
        self.splitter.addWidget(self.council_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([230, 700, 440])

        # Input area
        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        iv = QVBoxLayout(input_frame)
        iv.setContentsMargins(16, 8, 16, 10)
        iv.setSpacing(4)

        # Document indicator — hidden until a file is attached
        self.doc_indicator = QFrame()
        self.doc_indicator.setObjectName("docIndicator")
        di = QHBoxLayout(self.doc_indicator)
        di.setContentsMargins(8, 4, 8, 4)
        di.setSpacing(8)
        self.doc_label = QLabel()
        self.doc_label.setObjectName("docLabel")
        di.addWidget(self.doc_label)
        di.addStretch()
        clear_doc_btn = QPushButton("✕")
        clear_doc_btn.setObjectName("clearDocBtn")
        clear_doc_btn.setFixedSize(22, 22)
        clear_doc_btn.setToolTip("Remove attached document")
        clear_doc_btn.clicked.connect(self._clear_document)
        di.addWidget(clear_doc_btn)
        self.doc_indicator.setVisible(False)
        iv.addWidget(self.doc_indicator)

        il = QHBoxLayout()
        il.setSpacing(8)
        self.attach_btn = QPushButton("📎")
        self.attach_btn.setObjectName("attachBtn")
        self.attach_btn.setFixedWidth(38)
        self.attach_btn.setToolTip(
            "Attach a document\n(PDF, Word, Excel, PowerPoint, text/CSV/Markdown)"
        )
        self.attach_btn.clicked.connect(self._attach_document)
        il.addWidget(self.attach_btn)
        self.input = InputBox(self._send)
        il.addWidget(self.input)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setFixedWidth(110)
        self.send_btn.clicked.connect(self._send)
        il.addWidget(self.send_btn)
        iv.addLayout(il)

        # Status line
        self.status = QLabel("")
        self.status.setObjectName("statusLine")

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(top)
        cl.addWidget(self.splitter, 1)
        cl.addWidget(self.status)
        cl.addWidget(input_frame)
        self.setCentralWidget(central)

        self._update_council_panel_visibility()

    def _build_history_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("historyPanel")
        panel.setMinimumWidth(190)
        panel.setMaximumWidth(380)
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(6)

        header = QHBoxLayout()
        h = QLabel("Chats")
        h.setObjectName("panelHeader")
        header.addWidget(h)
        header.addStretch()
        self.select_all = QCheckBox("All")
        self.select_all.setToolTip("Select/deselect all")
        self.select_all.toggled.connect(self._toggle_select_all)
        header.addWidget(self.select_all)
        v.addLayout(header)

        btns = QHBoxLayout()
        new_b = QPushButton("+ New")
        new_b.clicked.connect(self._new_chat)
        btns.addWidget(new_b)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("dangerBtn")
        self.delete_btn.setToolTip("Delete the checked conversations")
        self.delete_btn.clicked.connect(self._delete_selected)
        btns.addWidget(self.delete_btn)
        v.addLayout(btns)

        self.history_list_container = QWidget()
        self.history_list_layout = QVBoxLayout(self.history_list_container)
        self.history_list_layout.setContentsMargins(0, 0, 0, 0)
        self.history_list_layout.setSpacing(2)
        self.history_list_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.history_list_container)
        scroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(scroll, 1)
        return panel

    # ---- Theme ------------------------------------------------------------ #
    def _apply_theme(self):
        fs = int(self.cfg.get("font_size", 14))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0f1419; color: #e6e9ef; }
            #topBar { background: #161b22; border-bottom: 1px solid #232a33; }
            #appTitle { color: #ffffff; }
            #panelHeader { color: #8ab4ff; font-weight: bold; }
            #panelHint { color: #7a8694; font-size: 12px; }
            #statusLine { color: #7a8694; padding: 4px 18px; }
            #userRow { background: #11161d; border-bottom: 1px solid #1c2530; }
            #aiRow { background: #0f1419; border-bottom: 1px solid #1c2530; }
            #authorBadge { color: #8ab4ff; }
            #aiRow #authorBadge { color: #6ee7b7; }
            QTextBrowser { color: #e6e9ef; }
            #inputFrame { background: #161b22; border-top: 1px solid #232a33; }
            QPlainTextEdit {
                background: #0f1419; border: 1px solid #2a3340; border-radius: 8px;
                padding: 8px; color: #e6e9ef;
            }
            QPlainTextEdit:focus { border: 1px solid #3b82f6; }
            QPushButton {
                background: #232a33; border: 1px solid #2a3340; border-radius: 8px;
                padding: 8px 14px; color: #e6e9ef;
            }
            QPushButton:hover { background: #2c3540; }
            #sendBtn { background: #3b82f6; border: none; font-weight: bold; }
            #sendBtn:hover { background: #2f6fe0; }
            #sendBtn:disabled { background: #2a3340; color: #6b7682; }
            #councilCard { background: #11161d; border: 1px solid #232a33; border-radius: 8px; }
            #councilHeader {
                background: transparent; border: none; padding: 10px;
                color: #cdd6e0; font-weight: bold; text-align: left;
            }
            #councilHeader:hover { color: #ffffff; }
            QComboBox, QDoubleSpinBox, QLineEdit {
                background: #0f1419; border: 1px solid #2a3340; border-radius: 6px;
                padding: 5px; color: #e6e9ef;
            }
            QCheckBox { color: #e6e9ef; }
            QScrollBar:vertical { background: #0f1419; width: 10px; }
            QScrollBar::handle:vertical { background: #2a3340; border-radius: 5px; }
            #historyPanel { background: #0c1015; border-right: 1px solid #232a33; }
            #historyRow { border-radius: 6px; }
            #historyRow[active="true"] { background: #1c2738; }
            #historyRow:hover { background: #161d27; }
            #historyTitle {
                background: transparent; border: none; padding: 6px 4px;
                color: #cdd6e0; text-align: left;
            }
            #historyTitle:hover { color: #ffffff; }
            #dangerBtn { color: #ffb4b4; }
            #dangerBtn:hover { background: #3a2326; border-color: #5a3035; }
            """
            + f"QTextBrowser {{ font-size: {fs}px; }}"
            + f" QPlainTextEdit {{ font-size: {fs}px; }}"
            + f" #historyTitle {{ font-size: {fs}px; }}"
            + """
            #attachBtn { background: #232a33; border: 1px solid #2a3340; border-radius: 8px; color: #e6e9ef; font-size: 17px; padding: 0; }
            #attachBtn:hover { background: #2c3540; }
            #attachBtn:disabled { color: #4a5560; }
            #docIndicator { background: #0d1f35; border: 1px solid #1e3a5f; border-radius: 6px; }
            #docLabel { color: #7ab4ff; font-size: 12px; }
            #clearDocBtn { background: transparent; border: none; color: #7a8694; font-size: 13px; padding: 0; min-width: 0; border-radius: 4px; }
            #clearDocBtn:hover { color: #ffffff; background: #2a3340; }
            """
        )

    # ---- Helpers ---------------------------------------------------------- #
    def _add_row(self, author: str, kind: str, text: str = "") -> MessageRow:
        row = MessageRow(author, kind)
        if text:
            row.set_markdown(text)
        # insert before the trailing stretch
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, row)
        self._scroll_to_bottom()
        return row

    def _add_system_note(self, text: str):
        self._add_row("System", "ai", text)

    def _scroll_to_bottom(self):
        bar = self.chat_scroll.verticalScrollBar()
        # defer so layout updates first
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _client(self) -> PerplexityClient | None:
        key = self.cfg.get("api_key", "")
        if not key:
            return None
        return PerplexityClient(key)

    def _update_council_panel_visibility(self):
        self.council_panel.setVisible(self.council_toggle.isChecked())

    # ---- Settings / toolbar actions -------------------------------------- #
    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self.model_ids, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.result_config()
            config.save(self.cfg)
            fill_model_combo(self.single_combo, self.cfg.get("single_model", "sonar-pro"),
                             self.model_ids)
            self.search_combo.setCurrentText(self.cfg.get("search_mode", "web"))
            self._apply_theme()
            for view in self.findChildren(MessageView):
                view.refresh()   # re-measure heights for the new font size
            self.status.setText("Settings saved.")

    def _on_council_toggle(self, checked: bool):
        self.cfg["council_enabled"] = checked
        config.save(self.cfg)
        self.single_combo.setEnabled(not checked)
        self._update_council_panel_visibility()

    def _on_single_changed(self, _index: int):
        self.cfg["single_model"] = self.single_combo.currentData()
        config.save(self.cfg)

    def _on_search_changed(self, text: str):
        self.cfg["search_mode"] = text
        config.save(self.cfg)
        self.status.setText(f"Search mode: {text}")

    def _new_chat(self):
        if self._running:
            return
        self._persist_current()
        self._start_new_conversation()
        self._refresh_history()
        self.status.setText("New conversation.")

    # ---- Conversation history (persistence) ------------------------------- #
    def _clear_chat_rows(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _start_new_conversation(self):
        self.current = store.Conversation.new()
        self.messages = self.current.messages
        self._clear_chat_rows()
        self._clear_council()

    def _persist_current(self):
        """Save the active conversation if it has any content."""
        if self.messages:
            if self.current.title in ("", "New chat"):
                first = next((m["content"] for m in self.messages
                              if m["role"] == "user"), "")
                self.current.title = store.title_from(first) or "New chat"
            store.save(self.current)

    def _refresh_history(self):
        while self.history_list_layout.count() > 1:
            item = self.history_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.history_rows = []
        for meta in store.list_all():
            row = HistoryRow(meta, self._open_conversation)
            row.set_active(meta["id"] == self.current.id)
            self.history_list_layout.insertWidget(
                self.history_list_layout.count() - 1, row)
            self.history_rows.append(row)
        self.select_all.blockSignals(True)
        self.select_all.setChecked(False)
        self.select_all.blockSignals(False)

    def _toggle_select_all(self, checked: bool):
        for row in self.history_rows:
            row.check.setChecked(checked)

    def _delete_selected(self):
        ids = [r.cid for r in self.history_rows if r.checked()]
        if not ids:
            self.status.setText("No chats selected.")
            return
        confirm = QMessageBox.question(
            self, "Delete chats",
            f"Delete {len(ids)} selected conversation(s)? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        for cid in ids:
            store.delete(cid)
        if self.current.id in ids:
            self._start_new_conversation()
        self._refresh_history()
        self.status.setText(f"Deleted {len(ids)} conversation(s).")

    def _open_conversation(self, cid: str):
        if self._running:
            return
        if cid == self.current.id:
            return
        self._persist_current()
        try:
            conv = store.load(cid)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Could not open chat: {e}")
            return
        self.current = conv
        self.messages = self.current.messages
        self._render_conversation()
        self._refresh_history()
        self.status.setText(f"Opened: {conv.title}")

    def _render_conversation(self):
        self._clear_chat_rows()
        self._clear_council()
        for m in self.messages:
            if m.get("role") == "user":
                self._add_row("You", "user", m.get("display") or m.get("content", ""))
            elif m.get("role") == "assistant":
                self._add_row("Assistant", "ai", m.get("content", ""))
        self._scroll_to_bottom()

    def _clear_council(self):
        self.sections.clear()
        # remove everything except header (index 0), hint (1), and trailing stretch
        while self.council_layout.count() > 3:
            item = self.council_layout.takeAt(2)
            w = item.widget()
            if w:
                w.deleteLater()

    # ---- Document attachment ---------------------------------------------- #
    def _attach_document(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach document", "", documents.FILTER
        )
        if not path:
            return
        try:
            text = documents.extract_text(path)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Could not read document: {e}")
            return
        self._doc_text = text
        self._doc_name = os.path.basename(path)
        self.doc_label.setText(f"📄  {self._doc_name}  ({len(text):,} chars extracted)")
        self.doc_indicator.setVisible(True)
        self.status.setText(f"Document attached: {self._doc_name}")

    def _clear_document(self):
        self._doc_text = ""
        self._doc_name = ""
        self.doc_indicator.setVisible(False)
        self.status.setText("Document removed.")

    # ---- Sending a turn --------------------------------------------------- #
    def _send(self):
        if self._running:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        client = self._client()
        if client is None:
            QMessageBox.warning(self, "No API key",
                                "Set your Perplexity API key in Settings first.")
            return

        self.input.clear()

        if self._doc_text:
            api_content = f"[Document: {self._doc_name}]\n{self._doc_text}\n\n---\n{text}"
            display_text = f"📄 *{self._doc_name}*\n\n{text}"
        else:
            api_content = text
            display_text = text

        self._add_row("You", "user", display_text)
        self.messages.append({"role": "user", "content": api_content, "display": display_text})
        self._current_question = text
        self._persist_current()   # title + save so it shows in the sidebar now
        self._refresh_history()

        if self.council_toggle.isChecked():
            self._run_council(client, text)   # bare question for synthesis prompt; history has doc
        else:
            self._run_single(client, text)

    def _set_running(self, running: bool):
        self._running = running
        self.send_btn.setEnabled(not running)
        self.input.setEnabled(not running)
        self.attach_btn.setEnabled(not running)
        self.send_btn.setText("…" if running else "Send")

    # ---- Single model path ----------------------------------------------- #
    def _run_single(self, client: PerplexityClient, question: str):
        self._set_running(True)
        model = self.single_combo.currentData()
        label = display_name(model)
        self.status.setText(f"Asking {label}…")
        self._assist_buffer = ""
        self._assist_row = self._add_row(label, "ai", "…")

        self.controller = CouncilController(self)
        self.controller.synthesisChunk.connect(self._on_chunk)
        self.controller.synthesisFinished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)
        # Reuse the synthesis streaming path with a single "member" == synth model
        # and no separate members: run the model directly as the synthesizer over
        # the raw history.
        history = list(self.messages)

        # Stream directly without the council fan-out.
        import threading

        def work():
            try:
                full = []
                cites = []
                for delta, c in client.stream(
                    model, history, self.cfg.get("temperature", 0.2),
                    self.cfg.get("search_mode", "web"),
                ):
                    if delta:
                        full.append(delta)
                        self.controller.synthesisChunk.emit(delta)
                    for u in c:
                        if u not in cites:
                            cites.append(u)
                self.controller.synthesisFinished.emit("".join(full), cites)
            except Exception as e:  # noqa: BLE001
                self.controller.failed.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    # ---- Council path ----------------------------------------------------- #
    def _run_council(self, client: PerplexityClient, question: str):
        self._set_running(True)
        self._clear_council()
        models = self.cfg.get("council_models", [])
        if not models:
            self._on_failed("No council members selected. Open Settings.")
            return

        # Cards are created on memberStarted, keyed by model id.
        self.status.setText(f"Consulting {len(models)} council members…")
        self._assist_buffer = ""
        self._assist_row = None  # created when synthesis starts

        self.controller = CouncilController(self)
        self.controller.memberStarted.connect(self._on_member_started)
        self.controller.memberFinished.connect(self._on_member_finished)
        self.controller.memberFailed.connect(self._on_member_failed)
        self.controller.synthesisStarted.connect(self._on_synth_started)
        self.controller.synthesisChunk.connect(self._on_chunk)
        self.controller.synthesisFinished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

        self.controller.run_turn(
            client=client,
            question=question,
            history=list(self.messages),
            council_models=models,
            synth_model=self.cfg.get("synth_model", "sonar-pro"),
            temperature=self.cfg.get("temperature", 0.2),
            search_mode=self.cfg.get("search_mode", "web"),
        )

    # ---- Controller slots ------------------------------------------------- #
    def _on_member_started(self, model: str):
        if model in self.sections:
            return
        sec = CollapsibleSection(f"⏳  {model}", expanded=False)
        sec.set_markdown("_Thinking…_")
        self.council_layout.insertWidget(self.council_layout.count() - 1, sec)
        self.sections[model] = sec

    def _on_member_finished(self, model: str, text: str, citations: list):
        sec = self.sections.get(model)
        if not sec:
            return
        body = text
        if citations:
            body += "\n\n**Sources**\n" + "\n".join(
                f"{i}. {u}" for i, u in enumerate(citations, 1)
            )
        sec.set_title(f"✓  {model}")
        sec.set_markdown(body)

    def _on_member_failed(self, model: str, error: str):
        sec = self.sections.get(model)
        if sec:
            sec.set_title(f"⚠  {model}")
            sec.set_markdown(f"_Failed: {error}_")

    def _on_synth_started(self):
        self.status.setText("Synthesizing council answer…")
        self._assist_buffer = ""
        self._assist_row = self._add_row("Council synthesis", "ai", "…")

    def _on_chunk(self, delta: str):
        if self._assist_row is None:
            self._assist_row = self._add_row("Answer", "ai", "")
        self._assist_buffer += delta
        self._assist_row.set_markdown(self._assist_buffer)
        self._scroll_to_bottom()

    def _on_finished(self, full_text: str, citations: list):
        text = full_text or self._assist_buffer
        # Persist clean text (without sources) to history for follow-ups.
        self.messages.append({"role": "assistant", "content": text})
        display = text
        if citations:
            display += "\n\n**Sources**\n" + "\n".join(
                f"{i}. {u}" for i, u in enumerate(citations, 1)
            )
        if self._assist_row is not None:
            self._assist_row.set_markdown(display)
        self._persist_current()   # save the completed turn
        self._refresh_history()
        self.status.setText("Done.")
        self._set_running(False)
        self._scroll_to_bottom()

    def _on_failed(self, error: str):
        if self._assist_row is not None:
            self._assist_row.set_markdown(f"**Error:** {error}")
        else:
            self._add_system_note(f"**Error:** {error}")
        self.status.setText("Error.")
        self._set_running(False)

    def closeEvent(self, event):
        self._persist_current()
        super().closeEvent(event)


def app_icon() -> QIcon:
    """Build the window/app icon from the rendered PNGs (falls back to the SVG,
    then to a plain coloured square)."""
    icon = QIcon()
    found = False
    for sz in (16, 32, 48, 64, 128, 256, 512):
        p = os.path.join(ASSETS_DIR, f"icon_{sz}.png")
        if os.path.exists(p):
            icon.addFile(p, QSize(sz, sz))
            found = True
    if found:
        return icon
    svg = os.path.join(ASSETS_DIR, "icon.svg")
    if os.path.exists(svg):
        return QIcon(svg)
    pm = QPixmap(64, 64)
    pm.fill(QColor("#3b82f6"))
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setWindowIcon(app_icon())
    win = ChatWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
