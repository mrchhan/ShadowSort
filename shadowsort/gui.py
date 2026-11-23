"""ShadowSort desktop UI (PySide6) — animated 'stage' + details view, Shadow blue/red theme."""

from __future__ import annotations

import os
import sys
import traceback

from PIL import Image, ImageOps
from PySide6.QtCore import (QSize, QEasingCurve, QObject, QPoint, QPropertyAnimation, QSettings, Qt, QThread,
                            QTimer, QUrl, Signal)
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGraphicsOpacityEffect, QListWidget, QListWidgetItem, QSpinBox,
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
    QSplitter, QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from . import __app_name__, __brand__, __version__
from .classifier import ai_available
from . import faces as F
from .engine import (DELETE_FOLDER, PEOPLE_FOLDER, Cancelled, Options, apply_plan, build_plan, empty_delete_folder,
                     latest_undo_log, undo)
from .stage import CYAN, GREEN, ORANGE, RED, Stage
from .styles import STYLES

STYLE = """
* { font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Inter', sans-serif; font-size: 10pt; color: #e8eefc; }
QMainWindow, QWidget#root { background: #060a14; }
QFrame#header { background: transparent; border-bottom: 1px solid #141c33; }
QLabel#brand { font-family: 'Cascadia Mono', Consolas, monospace; font-size: 10.5pt; font-weight: 700; letter-spacing: 1px; }
QLabel#byline { color: #ff8a3d; font-size: 8.5pt; font-weight: 600; letter-spacing: 0.5px; }
QLabel#mono, QLabel#stats { font-family: 'Cascadia Mono', Consolas, monospace; color: #7d8bb0; font-size: 9pt; letter-spacing: 1px; }
QFrame#cmd { background: #0b1122; border: 1px solid #1b2542; border-radius: 16px; }
QFrame#cmd:hover { border: 1px solid #27406e; }
QLabel#prompt { font-family: 'Cascadia Mono', Consolas, monospace; color: #03bbfe; font-weight: 700; }
QLineEdit#path { background: transparent; border: none; font-family: 'Cascadia Mono', Consolas, monospace; font-size: 10pt; padding: 4px; }
QLineEdit, QComboBox, QPlainTextEdit { background: #080d1a; border: 1px solid #1d2744; border-radius: 8px; padding: 6px 9px; selection-background-color: #1e9bff; }
QComboBox QAbstractItemView { color: #e8eefc; background: #0c1222; border: 1px solid #1d2744; selection-background-color: #1e6fd6; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox#styleBox { background: #0d1630; border: 1px solid #2d4f8f; border-radius: 8px; padding: 5px 10px;
    font-family: 'Cascadia Mono', Consolas, monospace; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; color: #8fd0ff; }
QPushButton { background: #111a30; border: 1px solid #1f2a4a; border-radius: 10px; padding: 8px 14px; font-weight: 600; }
QPushButton:hover { background: #17233f; border-color: #2b3d6b; }
QPushButton:disabled { color: #4c5878; background: #0b1020; border-color: #151d33; }
QPushButton#primary { border: none; color: white; padding: 9px 22px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #03bbfe, stop:0.45 #1e7bff, stop:1 #ff3b2f); }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2fd0ff, stop:0.45 #3d90ff, stop:1 #ff5a47); }
QPushButton#primary:disabled { background: #1a2238; color: #5d6a8e; }
QPushButton#danger { color: #ff7a6e; border-color: #4a1d22; background: #160b12; }
QPushButton#danger:hover { background: #241018; }
QPushButton#ghost { background: transparent; border: 1px solid transparent; color: #9fb0d8; padding: 6px 10px; }
QPushButton#ghost:hover { background: #10182c; border-color: #1f2a4a; }
QPushButton#seg { background: transparent; border: 1px solid #1f2a4a; border-radius: 0; padding: 6px 14px;
    font-family: 'Cascadia Mono', Consolas, monospace; font-size: 8.5pt; color: #7d8bb0; letter-spacing: 1px; }
QPushButton#seg:checked { background: #13203d; color: #e8eefc; border-color: #2d4f8f; }
QPushButton#segL { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
QPushButton#segR { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QFrame#drawer { background: #0a0f1e; border-left: 1px solid #1d2744; }
QLabel#h2 { font-family: 'Cascadia Mono', Consolas, monospace; color: #8fd0ff; font-size: 8.5pt; letter-spacing: 1.5px; font-weight: 700; margin-top: 10px; }
QLabel#muted { color: #7d8bb0; }
QFrame#personCard { background: #0c1222; border: 1px solid #1b2542; border-radius: 16px; }
QFrame#personCard:hover { border-color: #2d4f8f; }
QFrame#suggestBox { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0b1a33, stop:1 #1f0d16);
    border: 1px solid #2d4f8f; border-radius: 14px; }
QFrame#suggestChip { background: #0a0f1d; border: 1px solid #1f2a4a; border-radius: 12px; }
QPushButton#yes { background: #0f2c4f; border: 1px solid #1e9bff; color: #bfe6ff; padding: 3px 10px; font-size: 9pt; }
QPushButton#yes:hover { background: #1e4f86; }
QPushButton#no { background: transparent; border: 1px solid #4a1d22; color: #ff8a7e; padding: 3px 10px; font-size: 9pt; }
QPushButton#no:hover { background: #241018; }
QComboBox#mergeBox { combobox-popup: 0; }
QLineEdit#personName { font-weight: 600; font-size: 10.5pt; }
QDialog { background: #060a14; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #2b3a63; background: #080d1a; }
QCheckBox::indicator:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #03bbfe, stop:1 #ff3b2f); border: none; }
QSlider::groove:horizontal { height: 4px; background: #1d2744; border-radius: 2px; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #03bbfe, stop:1 #ff3b2f); border-radius: 2px; }
QSlider::handle:horizontal { background: white; width: 14px; margin: -6px 0; border-radius: 7px; }
QTableWidget, QTreeWidget { background: #0a0f1d; alternate-background-color: #0d1324; border: 1px solid #18213a; border-radius: 12px; gridline-color: #141c31; }
QHeaderView::section { background: #0e1528; border: none; padding: 7px; color: #7d8bb0; font-weight: 600; }
QTableWidget::item:selected, QTreeWidget::item:selected { background: #17305e; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; padding: 8px 16px; color: #7d8bb0; border-bottom: 2px solid transparent;
    font-family: 'Cascadia Mono', Consolas, monospace; font-size: 9pt; letter-spacing: 1px; }
QTabBar::tab:selected { color: #fff; border-bottom: 2px solid #1e9bff; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #1d2744; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QToolTip { background: #0c1222; color: #e8eefc; border: 1px solid #1d2744; }
"""

ORGANIZE = [("Category, then Year / Month", "both"), ("Category only", "category"), ("Year / Month only", "date")]
MATCH = [("Near-identical (recommended)", "near"), ("Exact copies only", "exact"),
         ("Similar shots / bursts (keeps best)", "similar")]


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def load_qimage(path: str, max_side: int = 520) -> QImage:
    """Thread-safe image loader (QImage, not QPixmap)."""
    try:
        with Image.open(path) as im:
            try:
                im.draft("RGB", (max_side * 2, max_side * 2))
            except Exception:
                pass
            im = ImageOps.exif_transpose(im).convert("RGBA")
            im.thumbnail((max_side, max_side))
            data = im.tobytes("raw", "RGBA")
            return QImage(data, im.width, im.height, QImage.Format.Format_RGBA8888).copy()
    except Exception:
        return QImage()


def round_pixmap(pm: QPixmap, size: int) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation))
    p.end()
    return out


class Worker(QObject):
    progress = Signal(str, int, int)
    log = Signal(str)
    photo = Signal(str, object)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel = False

    def run(self):
        try:
            self.done.emit(self.fn(self))
        except Cancelled:
            self.failed.emit("Cancelled.")
        except Exception as exc:
            self.log.emit(traceback.format_exc())
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# =============================================================================
# Details view (table / duplicates / log + preview)
# =============================================================================
class DetailsView(QWidget):
    def __init__(self):
        super().__init__()
        self.plan = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 14, 24, 8)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)

        self.tabs = QTabWidget()
        plan_tab = QWidget()
        pl = QVBoxLayout(plan_tab)
        pl.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(["All", "Kept", "To Delete"])
        self.folder = QComboBox()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search file or folder…")
        for w_ in (self.kind, self.folder):
            w_.currentIndexChanged.connect(self.fill_table)
        self.search.textChanged.connect(self.fill_table)
        row.addWidget(self.kind)
        row.addWidget(self.folder)
        row.addWidget(self.search, 1)
        pl.addLayout(row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Action", "Goes to", "Why"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 210)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(3, 230)
        self.table.itemSelectionChanged.connect(self._table_sel)
        pl.addWidget(self.table)
        self.tabs.addTab(plan_tab, "PLAN")

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Duplicate group", "Score", "Size", "Sharpness", "Date"])
        self.tree.setAlternatingRowColors(True)
        th = self.tree.header()
        th.setStretchLastSection(False)
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            th.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemSelectionChanged.connect(self._tree_sel)
        self.tabs.addTab(self.tree, "DUPLICATES")

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.tabs.addTab(self.log_box, "LOG")
        split.addWidget(self.tabs)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 40, 0, 0)
        self.preview = QLabel("Select a photo to preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(300, 300)
        self.preview.setStyleSheet("background:#080d1a;border:1px solid #18213a;border-radius:14px;color:#4c5878;")
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setObjectName("muted")
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sl.addWidget(self.preview, 1)
        sl.addWidget(self.details)
        split.addWidget(side)
        split.setSizes([700, 360])

    def set_plan(self, plan):
        self.plan = plan
        self.folder.blockSignals(True)
        self.folder.clear()
        self.folder.addItem("All folders", "")
        if plan:
            keys = []
            for a in plan.actions:
                k = os.path.relpath(a.dst, plan.options.output).split(os.sep)[0]
                if k not in keys:
                    keys.append(k)
            for k in sorted(keys, key=lambda k: (k == DELETE_FOLDER, k)):
                self.folder.addItem(k + "/", k)
        self.folder.blockSignals(False)
        self.fill_table()
        self.fill_tree()

    def show_folder(self, key):
        i = self.folder.findData(key)
        self.kind.setCurrentIndex(0)
        self.folder.setCurrentIndex(max(0, i))
        self.tabs.setCurrentIndex(0)

    def fill_table(self):
        self.table.setRowCount(0)
        if not self.plan:
            return
        kind = self.kind.currentIndex()
        folder = self.folder.currentData() or ""
        q = self.search.text().lower().strip()
        out = self.plan.options.output
        rows = []
        for a in self.plan.actions:
            if (kind == 1 and a.kind != "keep") or (kind == 2 and a.kind != "delete"):
                continue
            rel = os.path.relpath(os.path.dirname(a.dst), out)
            if folder and rel.split(os.sep)[0] != folder:
                continue
            if q and q not in os.path.basename(a.src).lower() and q not in rel.lower():
                continue
            rows.append((a, rel))
        self.table.setRowCount(len(rows))
        for r, (a, rel) in enumerate(rows):
            name = QTableWidgetItem(os.path.basename(a.src))
            name.setData(Qt.ItemDataRole.UserRole, a.src)
            name.setToolTip(a.src)
            act = QTableWidgetItem("Keep" if a.kind == "keep" else "Delete")
            act.setForeground(GREEN if a.kind == "keep" else RED)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, act)
            self.table.setItem(r, 2, QTableWidgetItem(rel))
            self.table.setItem(r, 3, QTableWidgetItem(a.reason))

    def fill_tree(self):
        self.tree.clear()
        if not self.plan:
            return
        for gi, g in enumerate(self.plan.groups, 1):
            top = QTreeWidgetItem([f"Group {gi} · {len(g)} photos · keeping {g[0].name}"])
            for i, p in enumerate(g):
                it = QTreeWidgetItem([("★ BEST  " if i == 0 else "✕  ") + p.name, f"{p.score:.0f}",
                                      f"{p.width}×{p.height}", f"{p.sharpness:.0f}",
                                      p.taken.strftime("%d %b %Y") if p.taken else ""])
                it.setData(0, Qt.ItemDataRole.UserRole, p.path)
                it.setForeground(0, CYAN if i == 0 else ORANGE)
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            top.setFirstColumnSpanned(True)
            top.setExpanded(gi <= 30)
        self.tabs.setTabText(1, f"DUPLICATES ({len(self.plan.groups)})")

    def _show(self, path):
        img = load_qimage(path)
        if img.isNull():
            self.preview.setText("Can't preview this file")
        else:
            self.preview.setPixmap(QPixmap.fromImage(img).scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        info = next((p for p in self.plan.photos if p.path == path), None) if self.plan else None
        act = next((a for a in self.plan.actions if a.src == path), None) if self.plan else None
        if not info:
            return
        size = f"{info.size_bytes / 1e6:.1f} MB" if info.size_bytes >= 1e6 else f"{info.size_bytes / 1e3:.0f} KB"
        lines = [f"<b style='color:#e8eefc'>{info.name}</b>", f"{info.width} × {info.height} · {size}"]
        if info.taken:
            lines.append(f"Taken {info.taken:%d %b %Y %H:%M} (from {info.date_source})")
        if info.camera:
            lines.append(info.camera)
        lines.append(f"Sharpness {info.sharpness:.0f} · Brightness {info.brightness:.0f}")
        if info.category:
            conf = info.extra.get("confidence")
            lines.append(f"Category: {info.category}" + (f" ({conf:.0%})" if conf else ""))
        if act:
            col = "#22d39a" if act.kind == "keep" else "#ff6b5e"
            lines.append(f"<span style='color:{col}'>→ {os.path.relpath(act.dst, self.plan.options.output)}</span>")
        if info.error:
            lines.append(f"<span style='color:#ff6b5e'>{info.error}</span>")
        self.details.setText("<br>".join(lines))

    def _table_sel(self):
        items = self.table.selectedItems()
        if items:
            self._show(self.table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    def _tree_sel(self):
        items = self.tree.selectedItems()
        if items and items[0].data(0, Qt.ItemDataRole.UserRole):
            self._show(items[0].data(0, Qt.ItemDataRole.UserRole))



# =============================================================================
# People view (face recognition)
# =============================================================================
def crop_pixmap(data: bytes, size: int) -> QPixmap:
    from .faces import CROP
    img = QImage(data, CROP, CROP, CROP * 3, QImage.Format.Format_RGB888).copy()
    return round_pixmap(QPixmap.fromImage(img), size)


def photo_with_box_qimage(path, box, side=230):
    """The whole original photo (scaled down for display) with this person's face outlined."""
    img = load_qimage(path, side)
    if img.isNull():
        return img
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    x, y, w, h = box
    W, H = img.width(), img.height()
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pad = 0.25
    r = QRectF((x - w * pad) * W, (y - h * pad) * H, w * (1 + 2 * pad) * W, h * (1 + 2 * pad) * H)
    p.setPen(QPen(QColor(0, 0, 0, 160), 4))
    p.drawRoundedRect(r, 6, 6)
    p.setPen(QPen(QColor("#03bbfe"), 2.2))
    p.drawRoundedRect(r, 6, 6)
    p.end()
    return img


class PhotosDialog(QDialog):
    """Every face in this person's group. Select the wrong ones and move them out."""

    def __init__(self, parent, view, person):
        super().__init__(parent)
        self.view, self.person = view, person
        self.changed = False
        self.setWindowTitle(f"{person.name} — {len(person.photos)} photos")
        self.resize(1100, 720)
        lay = QVBoxLayout(self)
        tip = QLabel("Every photo in this group. The blue box shows which face ShadowSort matched. If a box is on "
                     "someone else, select those photos (Ctrl/Shift-click) and move them out. Your original photos are "
                     "never changed.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.kinds = view.kinds_for(person)
        frow = QHBoxLayout()
        self.kind_filter = QComboBox()
        self.kind_filter.addItem("All photos", "")
        if self.kinds:
            kc = F.kind_counts(self.kinds)
            for k in F.KINDS:
                self.kind_filter.addItem(f"{k} ({kc[k]})", k)
        self.kind_filter.currentIndexChanged.connect(self._filter)
        frow.addWidget(self.kind_filter)
        frow.addStretch()
        lay.addLayout(frow)
        self.lst = QListWidget()
        self.lst.setViewMode(QListWidget.ViewMode.IconMode)
        self.lst.setIconSize(QSize(230, 230))
        self.lst.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.lst.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.lst.setSpacing(8)
        self.lst.setStyleSheet("QListWidget{background:#0a0f1d;border:none;}"
                               "QListWidget::item:selected{background:#5a1a22;border:2px solid #ff3b2f;border-radius:6px;}")
        faces = view.plan.faces
        for i in sorted(person.faces, key=lambda i: os.path.basename(faces[i].path))[:400]:
            f = faces[i]
            real = view.locate(f.path) or f.path
            img = photo_with_box_qimage(real, f.box)
            it = QListWidgetItem(QIcon(QPixmap.fromImage(img)) if not img.isNull() else QIcon(), os.path.basename(f.path))
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setData(Qt.ItemDataRole.UserRole + 1, self.kinds.get(f.path, ""))
            it.setToolTip(f"{real}\n{self.kinds.get(f.path, '')}")
            self.lst.addItem(it)
        lay.addWidget(self.lst, 1)
        row = QHBoxLayout()
        self.count = QLabel("Nothing selected")
        self.count.setObjectName("muted")
        self.lst.itemSelectionChanged.connect(self._sel)
        self.new_btn = QPushButton("Make a new person from selected")
        self.new_btn.setObjectName("primary")
        self.new_btn.clicked.connect(lambda: self._move(new=True))
        self.rm_btn = QPushButton(f"Not {person.name} — remove")
        self.rm_btn.setObjectName("danger")
        self.rm_btn.clicked.connect(lambda: self._move(new=False))
        row.addWidget(self.count, 1)
        row.addWidget(self.rm_btn)
        row.addWidget(self.new_btn)
        lay.addLayout(row)
        self._sel()

    def _filter(self):
        k = self.kind_filter.currentData()
        for r in range(self.lst.count()):
            it = self.lst.item(r)
            it.setHidden(bool(k) and it.data(Qt.ItemDataRole.UserRole + 1) != k)

    def _sel(self):
        n = len(self.lst.selectedItems())
        self.count.setText(f"{n} selected" if n else "Nothing selected")
        self.new_btn.setEnabled(n > 0 and n < self.lst.count())
        self.rm_btn.setEnabled(n > 0)

    def _move(self, new):
        idx = [it.data(Qt.ItemDataRole.UserRole) for it in self.lst.selectedItems()]
        if not idx:
            return
        F.split_faces(self.view.plan.people, self.view.plan.faces, self.person, idx, new_person=new)
        self.changed = True
        self.accept()


class LazyCombo(QComboBox):
    def __init__(self, fill):
        super().__init__()
        self._fill, self._filled = fill, False

    def showPopup(self):
        if not self._filled:
            self._filled = True
            self._fill(self)
        super().showPopup()


class ExportDialog(QDialog):
    """Choose which photos go into each person's ZIP."""

    def __init__(self, parent, people_count):
        super().__init__(parent)
        self.setWindowTitle("Export a ZIP per person")
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        t = QLabel(f"<b>{people_count} ZIP files</b>, one per person. Which photos should each ZIP contain?")
        t.setWordWrap(True)
        lay.addWidget(t)
        self.boxes = {}
        notes = {F.SOLO: "only that person in the photo",
                 F.SMALL: "with a few others (family, friends)",
                 F.GROUP: "big group photos (stage, family line-ups)"}
        for k in F.KINDS:
            b = QCheckBox(f"{k}  —  {notes[k]}")
            b.setChecked(k != F.GROUP)
            b.toggled.connect(self._check)
            self.boxes[k] = b
            lay.addWidget(b)
        self.split = QCheckBox("Keep Solo / Small Group / Group as folders inside the ZIP")
        self.split.setChecked(True)
        lay.addWidget(self.split)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Choose folder && export…")
        self.ok.setObjectName("primary")
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def _check(self):
        self.ok.setEnabled(any(b.isChecked() for b in self.boxes.values()))

    def kinds(self):
        return tuple(k for k, b in self.boxes.items() if b.isChecked())


class TogetherDialog(QDialog):
    """Pick 2+ people and get only the photos they are all in."""

    def __init__(self, parent, people, organized):
        super().__init__(parent)
        self.people = [p for p in people if not p.hidden]
        self.action = None
        self.setWindowTitle("Together — photos with all of these people")
        self.resize(460, 600)
        lay = QVBoxLayout(self)
        tip = QLabel("Tick two or more people, e.g. the bride and groom, to get only the photos they are all in.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.lst = QListWidget()
        self.lst.setIconSize(QSize(40, 40))
        self.lst.setStyleSheet("QListWidget{background:#0a0f1d;border:1px solid #1d2744;border-radius:10px;}"
                               "QListWidget::item{padding:4px;color:#e8eefc;}"
                               "QListWidget::indicator{width:18px;height:18px;border-radius:4px;border:1px solid #3b5590;"
                               "background:#080d1a;}"
                               "QListWidget::indicator:checked{border:none;background:qlineargradient(x1:0,y1:0,x2:1,"
                               "y2:1,stop:0 #03bbfe,stop:1 #ff3b2f);}")
        for p in self.people:
            it = QListWidgetItem(QIcon(crop_pixmap(p.crops[0], 40)) if p.crops else QIcon(),
                                 f"{p.name}   ·   {len(p.photos)} photos")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.lst.addItem(it)
        self.lst.itemChanged.connect(self._update)
        lay.addWidget(self.lst, 1)
        self.result = QLabel()
        lay.addWidget(self.result)
        row = QHBoxLayout()
        self.folder_btn = QPushButton("Add a Together folder")
        self.folder_btn.setToolTip("Makes By Person/Together/<names> with links — no extra space"
                                   + ("" if organized else " (created when you press Organize now)"))
        self.folder_btn.clicked.connect(lambda: self._done("folder"))
        self.zip_btn = QPushButton("Export ZIP…")
        self.zip_btn.setObjectName("primary")
        self.zip_btn.clicked.connect(lambda: self._done("zip"))
        row.addStretch()
        row.addWidget(self.folder_btn)
        row.addWidget(self.zip_btn)
        lay.addLayout(row)
        self._update()

    def chosen(self):
        return [p for r, p in enumerate(self.people) if self.lst.item(r).checkState() == Qt.CheckState.Checked]

    def _update(self, *_):
        ch = self.chosen()
        n = len(F.together_photos(ch)) if len(ch) >= 2 else 0
        if len(ch) < 2:
            self.result.setText("<span style='color:#7d8bb0'>Tick at least two people.</span>")
        else:
            self.result.setText(f"<b style='color:#03bbfe'>{n}</b> photos with "
                                + " & ".join(p.name for p in ch))
        for b in (self.folder_btn, self.zip_btn):
            b.setEnabled(n > 0)

    def _done(self, action):
        self.action = action
        self.accept()


class PersonCard(QFrame):
    def __init__(self, view, person):
        super().__init__()
        self.view, self.person = view, person
        self.setObjectName("personCard")
        self.setFixedWidth(232)
        self.setAcceptDrops(True)
        self.setToolTip("Drag this card onto another card to join them as one person")
        self._press = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        face = QLabel()
        if person.crops:
            face.setPixmap(crop_pixmap(person.crops[0], 84))
        face.setFixedSize(84, 84)
        top.addWidget(face)
        info = QVBoxLayout()
        cnt = QLabel(f"<b style='font-size:15pt'>{len(person.photos):,}</b> <span style='color:#7d8bb0'>photos</span>")
        info.addWidget(cnt)
        kinds = view.kinds_for(person)
        if kinds:
            kc = F.kind_counts(kinds)
            split = QLabel(f"<span style='color:#03bbfe'>{kc[F.SOLO]} solo</span> · "
                           f"<span style='color:#8fd0ff'>{kc[F.SMALL]} small</span> · "
                           f"<span style='color:#ff8a3d'>{kc[F.GROUP]} group</span>")
            split.setStyleSheet("font-size:9pt;")
            split.setToolTip("Solo = only this person · Small = 2 to "
                             f"{view.group_size() - 1} people · Group = {view.group_size()}+ people")
        else:
            split = None
        if person.known:
            badge = QLabel("● recognised")
            badge.setStyleSheet("color:#22d39a;font-size:8.5pt;")
            info.addWidget(badge)
        strip = QHBoxLayout()
        strip.setSpacing(2)
        for c in person.crops[1:5]:
            l = QLabel()
            l.setPixmap(crop_pixmap(c, 26))
            strip.addWidget(l)
        strip.addStretch()
        info.addLayout(strip)
        info.addStretch()
        top.addLayout(info)
        lay.addLayout(top)
        if split is not None:
            lay.addWidget(split)
        self.name = QLineEdit(person.name)
        self.name.setPlaceholderText(person.default_name)
        self.name.setObjectName("personName")
        self.name.editingFinished.connect(self._renamed)
        lay.addWidget(self.name)
        row = QHBoxLayout()
        photos = QPushButton("Photos / fix")
        photos.setObjectName("ghost")
        photos.clicked.connect(self._photos)
        self.hide_btn = QPushButton("Hide")
        self.hide_btn.setObjectName("ghost")
        self.hide_btn.setCheckable(True)
        self.hide_btn.setChecked(person.hidden)
        self.hide_btn.toggled.connect(self._hidden)
        self.merge = LazyCombo(self._fill_merge)
        self.merge.setObjectName("mergeBox")
        self.merge.setIconSize(QSize(30, 30))
        self.merge.addItem("Same person as…", None)
        # the drop-down list is a separate window: style it explicitly so names are readable on Windows
        view_ = self.merge.view()
        view_.setStyleSheet("QListView{background:#0c1222;color:#e8eefc;border:1px solid #2d4f8f;outline:0;}"
                            "QListView::item{min-height:36px;padding:2px 6px;color:#e8eefc;}"
                            "QListView::item:selected{background:#1e6fd6;color:white;}"
                            "QListView::item:hover{background:#17305e;color:white;}")
        self.merge.setMaxVisibleItems(12)
        self.merge.activated.connect(self._merge)
        row.addWidget(photos)
        row.addWidget(self.hide_btn)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(self.merge)
        self._hidden(person.hidden)

    def _photos(self):
        dlg = PhotosDialog(self, self.view, self.person)
        dlg.exec()
        if dlg.changed:
            QTimer.singleShot(0, self.view.rebuild)

    def _renamed(self):
        self.person.name = self.name.text().strip() or self.person.default_name
        self.view.refresh_summary()

    def _hidden(self, on):
        self.person.hidden = on
        self.hide_btn.setText("Show" if on else "Hide")
        if on:
            eff = QGraphicsOpacityEffect(self)
            eff.setOpacity(0.4)
            self.setGraphicsEffect(eff)
        else:
            self.setGraphicsEffect(None)
        self.view.refresh_summary()

    def _fill_merge(self, combo):
        """Filled only when opened: with 1,000+ people, building every list up front would freeze the app."""
        for other in self.view.plan.people:
            if other is not self.person and not other.hidden:
                icon = QIcon(crop_pixmap(other.crops[0], 30)) if other.crops else QIcon()
                combo.addItem(icon, f"{other.name}  ·  {len(other.photos)} photos", other.pid)

    def _merge(self, i):
        pid = self.merge.itemData(i)
        if pid is None:
            return
        target = next((p for p in self.view.plan.people if p.pid == pid), None)
        if target:
            self.view.merge(self.person, target)

    # drag a card onto another card = same person
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 12:
            return
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QDrag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-shadowsort-person", str(self.person.pid).encode())
        drag.setMimeData(mime)
        if self.person.crops:
            drag.setPixmap(crop_pixmap(self.person.crops[0], 64))
        self._press = None
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("application/x-shadowsort-person") and \
                int(bytes(e.mimeData().data("application/x-shadowsort-person")).decode()) != self.person.pid:
            self.setStyleSheet("QFrame#personCard{border:2px solid #03bbfe;}")
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.setStyleSheet("")

    def dropEvent(self, e):
        self.setStyleSheet("")
        pid = int(bytes(e.mimeData().data("application/x-shadowsort-person")).decode())
        src = next((p for p in self.view.plan.people if p.pid == pid), None)
        if src and src is not self.person:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.view.merge(src, self.person))


class SuggestionChip(QFrame):
    def __init__(self, view, a, b):
        super().__init__()
        self.setObjectName("suggestChip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        for p in (a, b):
            l = QLabel()
            if p.crops:
                l.setPixmap(crop_pixmap(p.crops[0], 46))
            l.setToolTip(f"{p.name} · {len(p.photos)} photos")
            lay.addWidget(l)
        txt = QLabel(f"<b>{a.name}</b><br><span style='color:#7d8bb0'>{b.name}</span>")
        lay.addWidget(txt)
        col = QVBoxLayout()
        col.setSpacing(4)
        yes = QPushButton("✓ Same")
        yes.setObjectName("yes")
        yes.clicked.connect(lambda: view.merge(b, a))
        no = QPushButton("✕ Different")
        no.setObjectName("no")
        no.clicked.connect(lambda: view.dismiss(a, b))
        col.addWidget(yes)
        col.addWidget(no)
        lay.addLayout(col)


class PeopleView(QWidget):
    exportRequested = Signal()
    openRequested = Signal()

    togetherRequested = Signal()
    PAGE = 60   # cards built at a time; big events can have 1,000+ people

    def __init__(self, locate, group_size=lambda: F.GROUP_SIZE):
        super().__init__()
        self.plan = None
        self.locate = locate
        self.group_size = group_size
        self._mains = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 8)
        head = QHBoxLayout()
        t = QLabel("PEOPLE")
        t.setObjectName("h2")
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        head.addWidget(t)
        head.addSpacing(12)
        head.addWidget(self.summary, 1)
        self.open_btn = QPushButton("Open people folder")
        self.open_btn.clicked.connect(self.openRequested.emit)
        self.export_btn = QPushButton("Export a ZIP per person…")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.exportRequested.emit)
        self.together_btn = QPushButton("Together…")
        self.together_btn.setToolTip("Photos that have two or more chosen people in them")
        self.together_btn.clicked.connect(self.togetherRequested.emit)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a person…")
        self.find.setFixedWidth(170)
        self.find.textChanged.connect(lambda _: self.rebuild(keep_mains=True))
        head.addWidget(self.find)
        head.addWidget(self.open_btn)
        head.addWidget(self.together_btn)
        head.addWidget(self.export_btn)
        lay.addLayout(head)
        tip = QLabel("Type a name under each face. If one person shows up twice, drag one card onto the other (or use "
                     "“Same person as…”). “Hide” leaves someone out. Names are remembered, so next time they're recognised automatically.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.suggest_box = QFrame()
        self.suggest_box.setObjectName("suggestBox")
        sb = QVBoxLayout(self.suggest_box)
        sb.setContentsMargins(14, 10, 14, 10)
        self.suggest_title = QLabel()
        self.suggest_title.setObjectName("h2")
        sb.addWidget(self.suggest_title)
        self.suggest_scroll = QScrollArea()
        self.suggest_scroll.setWidgetResizable(True)
        self.suggest_scroll.setFixedHeight(96)
        self.suggest_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.suggest_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.suggest_row_w = QWidget()
        self.suggest_row_w.setStyleSheet("background: transparent;")
        self.suggest_row = QHBoxLayout(self.suggest_row_w)
        self.suggest_row.setContentsMargins(0, 0, 0, 0)
        self.suggest_row.setSpacing(10)
        self.suggest_row.addStretch()
        self.suggest_scroll.setWidget(self.suggest_row_w)
        sb.addWidget(self.suggest_scroll)
        lay.addWidget(self.suggest_box)
        self.suggest_box.hide()
        self.dismissed = set()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.body.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.body)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)
        self.more_btn = QPushButton()
        self.more_btn.clicked.connect(self._more)
        self.more_btn.hide()
        lay.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self.page = self.PAGE
        self.cards = []
        self.empty = QLabel("No people yet. Turn on “Recognise faces” in Settings and press Sort these.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(self.empty, 0, 0)
        self.refresh_summary()

    def set_plan(self, plan):
        self.plan = plan
        self.page = self.PAGE
        self.rebuild()

    def _more(self):
        self.page += self.PAGE * 2
        self.rebuild(keep_mains=True)

    def kinds_for(self, person):
        if not self.plan or not self.plan.faces:
            return {}
        if self._mains is None:
            self._mains = F.main_faces(self.plan.faces)
        return F.person_photo_kinds(person, self.plan.faces, self._mains, self.group_size())

    def rebuild(self, keep_mains=False):
        if not keep_mains:
            self._mains = None
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        people = self.plan.people if self.plan else []
        q = self.find.text().strip().lower()
        if q:
            people = [p for p in people if q in p.name.lower()]
        self.empty.setVisible(not people)
        self.setUpdatesEnabled(False)
        for person in people[:self.page]:
            self.cards.append(PersonCard(self, person))
        self._place()
        self.setUpdatesEnabled(True)
        left = len(people) - len(self.cards)
        self.more_btn.setVisible(left > 0)
        self.more_btn.setText(f"Show more people ({left:,} left — people in fewer photos)")
        self.refresh_summary()
        if not keep_mains:
            self.refresh_suggestions()

    def refresh_suggestions(self):
        while self.suggest_row.count() > 1:
            w_ = self.suggest_row.takeAt(0).widget()
            if w_:
                w_.deleteLater()
        pairs = []
        if self.plan and self.plan.people:
            from .faces import suggest_pairs
            pairs = suggest_pairs(self.plan.people, self.plan.faces, limit=12, dismissed=self.dismissed)
        for i, (a, b) in enumerate(pairs):
            self.suggest_row.insertWidget(i, SuggestionChip(self, a, b))
        self.suggest_title.setText(f"SAME PERSON?  ·  {len(pairs)} possible match{'es' if len(pairs) != 1 else ''} "
                                   f"— tap ✓ to join them, or drag one card onto another")
        self.suggest_box.setVisible(bool(pairs))

    def merge(self, src, dst):
        """Join src into dst. Keeps the name you typed / the recognised name, else the bigger group."""
        from .faces import merge_people
        people = self.plan.people
        if src not in people or dst not in people:
            return
        keep_src = (src.renamed or src.known) and not (dst.renamed or dst.known)
        if keep_src or (not (dst.renamed or dst.known) and len(src.photos) > len(dst.photos)):
            src, dst = dst, src
        merge_people(people, self.plan.faces, src, dst)
        self.rebuild()

    def dismiss(self, a, b):
        self.dismissed.add((a.pid, b.pid))
        self.refresh_suggestions()

    def _place(self):
        cols = max(1, (self.scroll.viewport().width() - 10) // 246)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.cards:
            self._place()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._place)

    def refresh_summary(self):
        people = self.plan.people if self.plan else []
        shown = [p for p in people if not p.hidden]
        photos = set().union(*[p.photos for p in shown]) if shown else set()
        if not people:
            self.summary.setText("")
        else:
            extra = f" · {self.plan.unknown_faces} faces seen only once" if self.plan.unknown_faces else ""
            self.summary.setText(f"{len(shown)} people in {len(photos):,} photos{extra}")
        self.export_btn.setEnabled(bool(shown))
        self.together_btn.setEnabled(len(shown) >= 2)


# =============================================================================
# Settings drawer
# =============================================================================
class Drawer(QFrame):
    WIDTH = 380

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("drawer")
        self.setFixedWidth(self.WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(22, 16, 12, 6)
        t = QLabel("SETTINGS")
        t.setObjectName("brand")
        close = QPushButton("✕")
        close.setObjectName("ghost")
        close.clicked.connect(self.hide_drawer)
        head.addWidget(t)
        head.addStretch()
        head.addWidget(close)
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(22, 0, 22, 22)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        def h2(text):
            l = QLabel(text)
            l.setObjectName("h2")
            lay.addWidget(l)

        h2("OUTPUT FOLDER")
        row = QHBoxLayout()
        self.out = QLineEdit()
        self.out.setPlaceholderText("Where organized folders are created")
        b = QPushButton("…")
        b.setFixedWidth(40)
        b.clicked.connect(self._pick_out)
        row.addWidget(self.out)
        row.addWidget(b)
        lay.addLayout(row)
        self.subfolders = QCheckBox("Include subfolders")
        lay.addWidget(self.subfolders)

        h2("FOLDERS")
        self.organize = QComboBox()
        for text, _ in ORGANIZE:
            self.organize.addItem(text)
        lay.addWidget(self.organize)
        self.ai = QCheckBox("Recognise content with AI (offline)")
        lay.addWidget(self.ai)
        note = QLabel("AI pack installed ✓" if ai_available() else
                      "AI pack not installed — basic folders are used (Screenshots, Camera Photos, Images). "
                      "Run “run.bat ai” to add it.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("Extra AI folders, e.g. Motorbikes, Jewellery")
        lay.addWidget(self.extra)
        self.faces = QCheckBox("Recognise faces (a folder per person)")
        lay.addWidget(self.faces)
        fn = QLabel("Group photos appear in every person's folder as links — stored once, no extra space. "
                    "Face models download once (38 MB)." if F.available() else
                    "Needs OpenCV: pip install opencv-python-headless")
        fn.setObjectName("muted")
        fn.setWordWrap(True)
        lay.addWidget(fn)
        self.split_people = QCheckBox("Split each person into Solo / Small Group / Group")
        lay.addWidget(self.split_people)
        grow = QHBoxLayout()
        gl_ = QLabel("Big group starts at")
        self.group_size = QSpinBox()
        self.group_size.setRange(3, 30)
        self.group_size.setSuffix(" people")
        grow.addWidget(gl_)
        grow.addWidget(self.group_size)
        grow.addStretch()
        lay.addLayout(grow)
        mrow = QHBoxLayout()
        self.min_photos = QSpinBox()
        self.min_photos.setRange(2, 50)
        self.min_photos.setSuffix(" photos")
        self.min_photos.setToolTip("Big events have hundreds of guests. Raise this to only list people who "
                                   "appear in several photos.")
        mrow.addWidget(QLabel("Only list people in at least"))
        mrow.addWidget(self.min_photos)
        mrow.addStretch()
        lay.addLayout(mrow)
        self.group_folder = QCheckBox("Also make a “Group Photos” folder")
        lay.addWidget(self.group_folder)
        self.forget_btn = QPushButton("Forget saved names…")
        self.forget_btn.setObjectName("danger")
        self.forget_btn.setToolTip("Clears the people ShadowSort remembers from earlier runs")
        self.forget_btn.clicked.connect(self._forget)
        lay.addWidget(self.forget_btn)

        h2("DUPLICATES")
        self.match = QComboBox()
        for text, _ in MATCH:
            self.match.addItem(text)
        lay.addWidget(self.match)

        h2(f"SEND TO {DELETE_FOLDER.upper()}")
        self.j_blur = QCheckBox("Blurry photos")
        self.blur = QSlider(Qt.Orientation.Horizontal)
        self.blur.setRange(5, 80)
        self.blur_lbl = QLabel()
        self.blur_lbl.setObjectName("muted")
        self.blur.valueChanged.connect(lambda v: self.blur_lbl.setText(
            f"Blur sensitivity {v} · {'strict' if v > 45 else 'balanced' if v > 15 else 'only very blurry'}"))
        self.j_dark = QCheckBox("Blank, black or white photos")
        self.j_tiny = QCheckBox("Tiny images (under 300 px)")
        for x in (self.j_blur, self.blur, self.blur_lbl, self.j_dark, self.j_tiny):
            lay.addWidget(x)

        h2("SAFETY")
        self.copy_mode = QCheckBox("Copy instead of move (keep originals)")
        lay.addWidget(self.copy_mode)
        self.empty_btn = QPushButton(f"Empty {DELETE_FOLDER}…")
        self.empty_btn.setObjectName("danger")
        lay.addWidget(self.empty_btn)
        lay.addStretch()
        ver = QLabel(f"{__app_name__} v{__version__} · by {__brand__}")
        ver.setObjectName("mono")
        lay.addWidget(ver)

        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(260)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hide()

    def _forget(self):
        if QMessageBox.question(self, __app_name__, "Forget every name ShadowSort has learned? Your photos and "
                                "folders are not touched; people just won't be recognised automatically "
                                "until you name them again.") == QMessageBox.StandardButton.Yes:
            F.forget_all()
            QMessageBox.information(self, __app_name__, "Saved names cleared. Press Rescan to see fresh groups.")

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.out.text() or os.path.expanduser("~"))
        if d:
            self.out.setText(os.path.normpath(d))

    def place(self, top):
        p = self.parentWidget()
        self.setFixedHeight(p.height() - top)
        if self.isVisible() and self.anim.state() != QPropertyAnimation.State.Running:
            self.move(p.width() - self.WIDTH, top)
        self._top = top

    def toggle(self):
        self.hide_drawer() if self.isVisible() else self.show_drawer()

    def show_drawer(self):
        p = self.parentWidget()
        self.move(p.width(), self._top)
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setStartValue(QPoint(p.width(), self._top))
        self.anim.setEndValue(QPoint(p.width() - self.WIDTH, self._top))
        self.anim.start()

    def hide_drawer(self):
        if not self.isVisible():
            return
        p = self.parentWidget()
        self.anim.stop()
        self.anim.setStartValue(self.pos())
        self.anim.setEndValue(QPoint(p.width(), self._top))
        try:
            self.anim.finished.disconnect()
        except Exception:
            pass
        self.anim.finished.connect(self._after_hide)
        self.anim.start()

    def _after_hide(self):
        self.anim.finished.disconnect()
        self.hide()


# =============================================================================
# Main window
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{__app_name__} — by {__brand__}")
        icon = resource_path("assets", "icon.ico")
        if os.path.exists(icon):
            self.setWindowIcon(QIcon(icon))
        self.resize(1360, 860)
        self.setAcceptDrops(True)
        self.settings = QSettings(__brand__, __app_name__)
        if not self.settings.allKeys():  # bring over settings from versions branded "AIShadow"
            old = QSettings("AIShadow", __app_name__)
            for k in old.allKeys():
                self.settings.setValue(k, old.value(k))
        self.plan = None
        self.thread = None
        self.worker = None
        self.state = "idle"  # idle | scanning | preview | applying | done

        logo = QPixmap(resource_path("assets", "shadow-logo-round.png"))
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        self.root = root
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # header -------------------------------------------------------------
        header = QFrame()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(22, 12, 18, 12)
        lg = QLabel()
        if not logo.isNull():
            lg.setPixmap(round_pixmap(logo, 30))
        brand = QLabel("<span style='color:#03bbfe'>SHADOW</span><span style='color:#ff3b2f'>SORT</span>"
                       "<span style='color:#3a4668'>&nbsp;&nbsp;/&nbsp;&nbsp;</span>"
                       "<span style='color:#7d8bb0'>PHOTO ORGANIZER</span>")
        brand.setObjectName("brand")
        byline = QLabel(f"by {__brand__}")
        byline.setObjectName("byline")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(brand)
        col.addWidget(byline)
        hl.addWidget(lg)
        hl.addSpacing(8)
        hl.addLayout(col)
        hl.addStretch()
        self.stats = QLabel("")
        self.stats.setObjectName("stats")
        hl.addWidget(self.stats)
        hl.addSpacing(16)
        sty = QLabel("STYLE")
        sty.setObjectName("mono")
        self.style_box = QComboBox()
        self.style_box.setObjectName("styleBox")
        for st_cls in STYLES:
            self.style_box.addItem(st_cls.name, st_cls.key)
            self.style_box.setItemData(self.style_box.count() - 1, st_cls.blurb, Qt.ItemDataRole.ToolTipRole)
        self.style_box.setMinimumWidth(130)
        hl.addWidget(sty)
        hl.addWidget(self.style_box)
        hl.addSpacing(12)
        self.seg_stage = QPushButton("STAGE")
        self.seg_people = QPushButton("PEOPLE")
        self.seg_details = QPushButton("DETAILS")
        for b, extra in ((self.seg_stage, "segL"), (self.seg_people, "segM"), (self.seg_details, "segR")):
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setProperty("class", extra)
        self.seg_stage.setStyleSheet("border-top-left-radius:8px;border-bottom-left-radius:8px;")
        self.seg_details.setStyleSheet("border-top-right-radius:8px;border-bottom-right-radius:8px;border-left:none;")
        self.seg_stage.setChecked(True)
        self.seg_stage.clicked.connect(lambda: self._view(0))
        self.seg_details.clicked.connect(lambda: self._view(1))
        self.seg_people.setStyleSheet("border-left:none;")
        self.seg_people.clicked.connect(lambda: self._view(2))
        hl.addWidget(self.seg_stage)
        hl.addWidget(self.seg_people)
        hl.addWidget(self.seg_details)
        hl.addSpacing(8)
        gear = QPushButton("⚙  Settings")
        gear.setObjectName("ghost")
        gear.clicked.connect(lambda: self.drawer.toggle())
        hl.addWidget(gear)
        outer.addWidget(header)
        self.header = header

        # stage / details ------------------------------------------------------
        self.stack = QStackedWidget()
        self.stage = Stage(logo)
        self.stage.cardClicked.connect(self._card_clicked)
        self.style_box.currentIndexChanged.connect(self._style_changed)
        self.details = DetailsView()
        self.people = PeopleView(self._locate, group_size=lambda: self.drawer.group_size.value())
        self.people.exportRequested.connect(self.export_people)
        self.people.togetherRequested.connect(self.together)
        self.people.openRequested.connect(
            lambda: self._open(os.path.join(self.drawer.out.text(), PEOPLE_FOLDER)))
        self.stack.addWidget(self.stage)
        self.stack.addWidget(self.details)
        self.stack.addWidget(self.people)
        outer.addWidget(self.stack, 1)

        # command bar ----------------------------------------------------------
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(22, 6, 22, 18)
        cmd = QFrame()
        cmd.setObjectName("cmd")
        cl = QHBoxLayout(cmd)
        cl.setContentsMargins(16, 6, 6, 6)
        prompt = QLabel("shadow ›")
        prompt.setObjectName("prompt")
        self.src = QLineEdit()
        self.src.setObjectName("path")
        self.src.setPlaceholderText("drop a photo folder here, or click Browse…")
        self.src.textChanged.connect(self._src_changed)
        self.src.returnPressed.connect(self._primary)
        browse = QPushButton("Browse")
        browse.setObjectName("ghost")
        browse.clicked.connect(self._pick_src)
        self.primary = QPushButton("Sort these")
        self.primary.setObjectName("primary")
        self.primary.clicked.connect(self._primary)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        cl.addWidget(prompt)
        cl.addWidget(self.src, 1)
        cl.addWidget(browse)
        cl.addWidget(self.cancel_btn)
        cl.addWidget(self.primary)
        bl.addWidget(cmd, 1)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self.scan)
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(self.do_undo)
        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(lambda: self._open(self.drawer.out.text()))
        for b in (self.rescan_btn, self.undo_btn, self.open_btn):
            bl.addWidget(b)
        outer.addWidget(bar)

        self.drawer = Drawer(root)
        self.drawer.empty_btn.clicked.connect(self.do_empty)
        self.drawer.copy_mode.toggled.connect(self._refresh)
        self.drawer.group_size.valueChanged.connect(lambda _: self.people.rebuild() if self.people.plan else None)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self._update_stats)
        self.clock.start(100)

        self._load_settings()
        self._refresh()

    # ----------------------------------------------------------------- layout
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.drawer.place(self.header.height())

    def showEvent(self, e):
        super().showEvent(e)
        self.drawer.place(self.header.height())

    def _style_changed(self, _=None):
        key = self.style_box.currentData()
        self.stage.set_style(key)
        self.settings.setValue("style", key)

    def _view(self, i):
        self.stack.setCurrentIndex(i)
        self.seg_stage.setChecked(i == 0)
        self.seg_details.setChecked(i == 1)
        self.seg_people.setChecked(i == 2)

    def _update_stats(self):
        n = len(self.stage.tiles)
        el = self.stage.elapsed()
        self.stats.setText(f"{n:,} PHOTOS     {el:05.1f}s" if n or el else f"v{__version__}")

    # --------------------------------------------------------------- settings
    def _load_settings(self):
        s, d = self.settings, self.drawer
        i = self.style_box.findData(s.value("style", "mosaic"))
        self.style_box.setCurrentIndex(max(0, i))
        self._style_changed()
        self.src.setText(s.value("src", ""))
        if s.value("out", ""):
            d.out.setText(s.value("out", ""))
        d.subfolders.setChecked(s.value("subfolders", True, type=bool))
        d.organize.setCurrentIndex(s.value("organize", 0, type=int))
        d.match.setCurrentIndex(s.value("match", 0, type=int))
        d.ai.setChecked(s.value("ai", True, type=bool))
        d.extra.setText(s.value("extra", ""))
        d.j_blur.setChecked(s.value("j_blur", True, type=bool))
        d.blur.setValue(s.value("blur", 20, type=int))
        d.blur.valueChanged.emit(d.blur.value())
        d.j_dark.setChecked(s.value("j_dark", True, type=bool))
        d.j_tiny.setChecked(s.value("j_tiny", False, type=bool))
        d.copy_mode.setChecked(s.value("copy", False, type=bool))
        d.faces.setChecked(s.value("faces", True, type=bool) and F.available())
        d.split_people.setChecked(s.value("split_people", True, type=bool))
        d.group_size.setValue(s.value("group_size", F.GROUP_SIZE, type=int))
        d.group_folder.setChecked(s.value("group_folder", True, type=bool))
        d.min_photos.setValue(s.value("min_photos", 2, type=int))

    def _save_settings(self):
        d = self.drawer
        for k, v in {"src": self.src.text(), "out": d.out.text(), "subfolders": d.subfolders.isChecked(),
                     "organize": d.organize.currentIndex(), "match": d.match.currentIndex(),
                     "ai": d.ai.isChecked(), "extra": d.extra.text(), "j_blur": d.j_blur.isChecked(),
                     "blur": d.blur.value(), "j_dark": d.j_dark.isChecked(), "j_tiny": d.j_tiny.isChecked(),
                     "copy": d.copy_mode.isChecked(), "faces": d.faces.isChecked(),
                     "split_people": d.split_people.isChecked(), "group_size": d.group_size.value(),
                     "group_folder": d.group_folder.isChecked(), "min_photos": d.min_photos.value()}.items():
            self.settings.setValue(k, v)

    def closeEvent(self, e):
        self._save_settings()
        super().closeEvent(e)

    def _options(self) -> Options:
        d = self.drawer
        return Options(
            source=self.src.text().strip(), output=d.out.text().strip(),
            organize_by=ORGANIZE[d.organize.currentIndex()][1], match_level=MATCH[d.match.currentIndex()][1],
            include_subfolders=d.subfolders.isChecked(), use_ai=d.ai.isChecked(),
            extra_categories=[x for x in d.extra.text().split(",") if x.strip()],
            junk_blurry=d.j_blur.isChecked(), junk_dark_blank=d.j_dark.isChecked(), junk_tiny=d.j_tiny.isChecked(),
            blur_threshold=float(d.blur.value()), copy_instead_of_move=d.copy_mode.isChecked(),
            faces=d.faces.isChecked(), split_people=d.split_people.isChecked(),
            group_size=d.group_size.value(), group_folder=d.group_folder.isChecked(),
            min_person_photos=d.min_photos.value(),
        )

    # ---------------------------------------------------------------- helpers
    def _src_changed(self, text):
        if self.state in ("preview", "done"):
            self.state = "idle"
            self.plan = None
            self.stage.reset()
        if text and os.path.isdir(text):
            self.drawer.out.setText(os.path.join(text, "ShadowSort Organized"))
        self._refresh()

    def _pick_src(self):
        d = QFileDialog.getExistingDirectory(self, "Choose your photo folder", self.src.text() or os.path.expanduser("~"))
        if d:
            self.src.setText(os.path.normpath(d))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.isdir(p):
                self.src.setText(os.path.normpath(p))
                if not self._busy():
                    self.scan()
                break

    def _open(self, path):
        if path and os.path.isdir(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _busy(self):
        return self.thread is not None

    def _refresh(self):
        busy = self._busy()
        copy = self.drawer.copy_mode.isChecked()
        self.cancel_btn.setVisible(busy)
        self.primary.setEnabled(not busy)
        if self.state == "preview":
            self.primary.setText("Copy now" if copy else "Organize now")
        elif self.state == "done":
            self.primary.setText("Sort another")
        else:
            self.primary.setText("Sort these")
        self.rescan_btn.setVisible(self.state == "preview" and not busy)
        self.undo_btn.setEnabled(not busy)
        self.open_btn.setEnabled(not busy)
        self.drawer.empty_btn.setEnabled(not busy)

    def _primary(self):
        if self._busy():
            return
        if self.state == "preview":
            self.apply()
        elif self.state == "done":
            self.state = "idle"
            self.stage.reset()
            self._pick_src()
            self._refresh()
        else:
            self.scan()

    def _log(self, msg):
        self.details.log_box.appendPlainText(msg)

    def _run(self, fn, on_done):
        self.thread = QThread()
        self.worker = Worker(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        q = Qt.ConnectionType.QueuedConnection
        self.worker.progress.connect(self._progress, q)
        self.worker.log.connect(self._log, q)
        self.worker.photo.connect(self._photo, q)
        self.worker.done.connect(self._finish, q)
        self.worker.failed.connect(self._failed, q)
        self._on_done = on_done
        self.thread.start()
        self._refresh()

    def _cleanup(self):
        if self.thread:
            self.thread.quit()
            self.thread.wait()
        self.thread = None
        self.worker = None
        self._refresh()

    def _finish(self, result):
        cb = self._on_done
        self._cleanup()
        cb(result)

    def _failed(self, msg):
        self._cleanup()
        if self.state == "scanning":
            self.state = "idle"
            self.stage.reset("cancelled" if msg == "Cancelled." else "something went wrong — see Details › Log")
        self._refresh()
        if msg != "Cancelled.":
            QMessageBox.warning(self, __app_name__, f"Something went wrong:\n\n{msg}\n\nSee Details › Log.")

    def _cancel(self):
        if self.worker:
            self.worker.cancel = True
            self.stage.set_status("cancelling…", RED)

    def _progress(self, stage, done, total):
        if stage == "Analysing photos":
            self.stage.set_total(total)
            self.stage.set_status(f"reading photos · {done:,} / {total:,}", CYAN)
        elif stage == "Recognising content":
            self.stage.set_status(f"recognising content · {done:,} / {total:,}", CYAN)
        elif stage == "Finding duplicates":
            self.stage.set_status("comparing photos · finding duplicates", ORANGE)
        elif stage == "Organising":
            self.stage.set_status(f"moving photos · {done:,} / {total:,}", ORANGE)
        elif stage == "Finding faces":
            self.stage.set_status(f"finding faces · {done:,} / {total:,}", ORANGE)
        elif stage == "Grouping faces":
            self.stage.set_status(f"grouping faces into people · {done:,} / {total:,}", ORANGE)
        elif stage == "Preparing people":
            self.stage.set_status(f"preparing people · {done:,} / {total:,}", ORANGE)
        elif stage == "Making people folders":
            self.stage.set_status(f"making people folders · {done:,} / {total:,}", ORANGE)
        elif stage == "Exporting":
            self.stage.set_status(f"exporting · {done:,} / {total:,} photos", ORANGE)
        elif stage == "Undoing":
            self.stage.set_status(f"restoring · {done:,} / {total:,}", ORANGE)
        else:
            self.stage.set_status(stage.lower(), CYAN)

    def _photo(self, path, thumb):
        self.stage.add_photo(path, thumb)

    # ---------------------------------------------------------------- actions
    def scan(self):
        opts = self._options()
        if not os.path.isdir(opts.source):
            self._pick_src()
            opts = self._options()
            if not os.path.isdir(opts.source):
                return
        if not opts.output:
            opts.output = os.path.join(opts.source, "ShadowSort Organized")
            self.drawer.out.setText(opts.output)
        self._save_settings()
        self.details.log_box.clear()
        self.plan = None
        self.details.set_plan(None)
        self.people.set_plan(None)
        self.state = "scanning"
        self.stage.start_scan()
        self._view(0)

        def job(w: Worker):
            plan = build_plan(opts, progress=w.progress.emit, cancelled=lambda: w.cancel, log=w.log.emit,
                              on_photo=lambda info: w.photo.emit(info.path, info.extra.pop("thumb", None)))
            # cover photos for each folder card (best 3)
            covers = {}
            by_key = {}
            info = {p.path: p for p in plan.photos}
            for a in plan.actions:
                key = os.path.relpath(a.dst, plan.options.output).split(os.sep)[0]
                by_key.setdefault(key, []).append(info[a.src])
            for key, items in by_key.items():
                items = [p for p in items if p.ok] or items
                items.sort(key=lambda p: -(p.sharpness * min(1.0, p.contrast / 40)))
                covers[key] = [load_qimage(p.path, 220) for p in items[:3]]
            faces_cov = [QImage(c, F.CROP, F.CROP, F.CROP * 3, QImage.Format.Format_RGB888).copy()
                         for p in plan.people[:3] for c in p.crops[:1]]
            if faces_cov:
                covers[PEOPLE_FOLDER] = faces_cov
            return plan, covers

        self._run(job, self._show_plan)

    def _show_plan(self, result):
        plan, covers = result
        self.plan = plan
        self.state = "preview"
        self.details.set_plan(plan)
        self.people.set_plan(plan)
        self.stage.show_plan(plan, {k: [QPixmap.fromImage(i) for i in v if not i.isNull()] for k, v in covers.items()})
        self._refresh()

    def _card_clicked(self, key):
        if key == PEOPLE_FOLDER:
            self._view(2)
            return
        self.details.show_folder(key)
        self._view(1)

    def _locate(self, src):
        """Where an original photo is right now (moved after Organize, original before)."""
        if self.plan and self.state == "done":
            for a in self.plan.actions:
                if a.src == src and a.kind == "keep":
                    return a.dst if os.path.exists(a.dst) else None
            return None
        return src if os.path.exists(src) else None

    def _current_locate(self):
        if self.state == "done":
            where = {a.src: a.dst for a in self.plan.actions if a.kind == "keep"}
            return lambda s: where.get(s) if where.get(s) and os.path.exists(where[s]) else None  # noqa: E731
        return lambda s: s if os.path.exists(s) else None  # noqa: E731

    def _pick_target(self, title):
        out = self.drawer.out.text()
        default = out if out and os.path.isdir(out) else os.path.expanduser("~")
        return QFileDialog.getExistingDirectory(self, title, default)

    def export_people(self):
        if not self.plan or not self.plan.people or self._busy():
            return
        people = [p for p in self.plan.people if not p.hidden]
        dlg = ExportDialog(self, len(people))
        if not dlg.exec():
            return
        kinds, split = dlg.kinds(), dlg.split.isChecked()
        target = self._pick_target("Where should the ZIP files go?")
        if not target:
            return
        locate, faces, gs = self._current_locate(), self.plan.faces, self.drawer.group_size.value()

        def job(w: Worker):
            return F.export_zips(people, locate, target, progress=lambda d, t: w.progress.emit("Exporting", d, t),
                                 faces=faces, kinds=kinds, group_size=gs, split=split)

        def done(paths):
            self.stage.set_status(f"exported {len(paths)} ZIP files · {', '.join(kinds).lower()}", GREEN)
            self._open(target)

        self._run(job, done)

    def together(self):
        if not self.plan or self._busy():
            return
        dlg = TogetherDialog(self, self.plan.people, self.state == "done")
        if not dlg.exec() or not dlg.action:
            return
        chosen = dlg.chosen()
        names = " & ".join(p.name for p in chosen)
        if dlg.action == "zip":
            target = self._pick_target("Where should the ZIP go?")
            if not target:
                return
            locate = self._current_locate()

            def job(w: Worker):
                return F.export_together_zip(chosen, locate, target,
                                             progress=lambda d, t: w.progress.emit("Exporting", d, t))

            def done(path):
                self.stage.set_status(f"exported {names}.zip", GREEN)
                self._open(target)

            self._run(job, done)
            return
        self.plan.together.append([p.name for p in chosen])
        if self.state == "done":
            from .engine import make_links, person_link_actions
            acts = [a for a in person_link_actions(self.plan) if os.sep + "Together" + os.sep in a.dst
                    and names.replace("/", "_") in a.dst]
            n = make_links(self.plan, acts)
            QMessageBox.information(self, __app_name__, f"Made By Person/Together/{names} with {n} photos.")
            self._open(os.path.join(self.drawer.out.text(), PEOPLE_FOLDER, "Together"))
        else:
            QMessageBox.information(self, __app_name__, f"“{names}” will get its own folder in By Person/Together "
                                    "when you press Organize now.")

    def apply(self):
        if not self.plan:
            return
        self.stage.finish_now()
        d = self.drawer  # People settings can be changed after the scan
        self.plan.options.split_people = d.split_people.isChecked()
        self.plan.options.group_size = d.group_size.value()
        self.plan.options.group_folder = d.group_folder.isChecked()
        st = self.plan.stats
        verb = "Copy" if self.plan.options.copy_instead_of_move else "Move"
        msg = (f"{verb} {st['keep']:,} photos into their folders and {st['duplicates'] + st['junk']:,} into "
               f"“{DELETE_FOLDER}”?\n\nNothing is permanently deleted, and Undo puts everything back.")
        if QMessageBox.question(self, __app_name__, msg) != QMessageBox.StandardButton.Yes:
            return
        plan = self.plan
        self.state = "applying"

        def job(w: Worker):
            log = apply_plan(plan, progress=w.progress.emit, cancelled=lambda: w.cancel)
            if plan.people:
                try:
                    n = F.save_known(plan.people, plan.faces)
                    w.log.emit(f"Remembered {n} named people for next time.")
                except Exception as exc:
                    w.log.emit(f"Could not save people names: {exc}")
            return log

        def done(log_path):
            self.state = "done"
            self._log(f"Undo log: {log_path}")
            st = plan.stats
            ppl = sum(not p.hidden for p in plan.people)
            extra = f" · {ppl} people folders" if ppl else ""
            self.stage.set_status(f"done · {st['categories']} folders{extra} · {st['duplicates'] + st['junk']:,} to "
                                  f"{DELETE_FOLDER} · nothing deleted", GREEN)
            self._refresh()
            self._open(plan.options.output)

        self._run(job, done)

    def do_undo(self):
        out = self.drawer.out.text().strip()
        log = latest_undo_log(out) if out else None
        if not log:
            QMessageBox.information(self, __app_name__, "There is nothing to undo in this output folder.")
            return
        if QMessageBox.question(self, __app_name__, "Put every photo back where it was before the last run?") \
                != QMessageBox.StandardButton.Yes:
            return

        def job(w: Worker):
            return undo(log, progress=w.progress.emit)

        def done(n):
            self.state = "idle"
            self.plan = None
            self.details.set_plan(None)
            self.people.set_plan(None)
            self.stage.reset(f"undo complete · {n:,} photos restored")
            self._refresh()

        self._run(job, done)

    def do_empty(self):
        out = self.drawer.out.text().strip()
        folder = os.path.join(out, DELETE_FOLDER)
        if not os.path.isdir(folder):
            QMessageBox.information(self, __app_name__, f"There is no “{DELETE_FOLDER}” folder yet.")
            return
        if QMessageBox.warning(self, __app_name__,
                               f"Send everything in\n{folder}\nto the Recycle Bin?\n\nUndo can't bring these back.",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return
        n = empty_delete_folder(out)
        self.stage.set_status(f"removed {n:,} files from {DELETE_FOLDER}", RED)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ShadowCreativeStudio.ShadowSort")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName(__brand__)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
