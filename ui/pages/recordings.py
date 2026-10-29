"""Recordings page: browse the clips and snapshots this application has written."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.context import AppContext
from ui.widgets.common import EmptyState

_VIDEO_SUFFIXES = {".mp4", ".avi", ".mkv", ".mov", ".m4v", ".wmv"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def _human_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class RecordingsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._entries: list[tuple[str, Path]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        bar = QFrame()
        bar.setObjectName("toolbar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(9)
        bar_layout.addWidget(QLabel("Show"))
        self._filter = QComboBox()
        self._filter.addItem("Everything", "all")
        self._filter.addItem("Recordings only", "recording")
        self._filter.addItem("Snapshots only", "snapshot")
        self._filter.setMinimumWidth(160)
        self._filter.currentIndexChanged.connect(lambda _i: self.refresh())
        bar_layout.addWidget(self._filter)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        bar_layout.addWidget(refresh_btn)

        bar_layout.addStretch(1)

        open_btn = QPushButton("Open file")
        open_btn.setObjectName("ghost")
        open_btn.clicked.connect(self._open_selected)
        bar_layout.addWidget(open_btn)

        folder_btn = QPushButton("Open folder")
        folder_btn.setObjectName("ghost")
        folder_btn.clicked.connect(self._open_folder)
        bar_layout.addWidget(folder_btn)

        delete_btn = QPushButton("Delete selected")
        delete_btn.setObjectName("danger")
        delete_btn.clicked.connect(self._delete_selected)
        bar_layout.addWidget(delete_btn)

        root.addWidget(bar)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Type", "File", "Size", "Modified"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setHighlightSections(False)
        self._table.doubleClicked.connect(lambda _i: self._open_selected())

        self._empty = EmptyState(
            "Nothing recorded yet",
            "Use the Snapshot and Record buttons on the Live Cameras page, or enable "
            "evidence snapshots in Settings. Files are stored locally under data/.",
            "recordings",
        )
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        footer = QHBoxLayout()
        self._count = QLabel("0 files")
        self._count.setObjectName("dim")
        footer.addWidget(self._count)
        footer.addStretch(1)
        paths = QLabel(
            f"recordings: {self._ctx.recording_dir}   ·   snapshots: {self._ctx.snapshot_dir}"
        )
        paths.setObjectName("dim")
        footer.addWidget(paths)
        root.addLayout(footer)

        self.refresh()

    # -- scanning ----------------------------------------------------------
    def refresh(self) -> None:
        mode = str(self._filter.currentData() or "all")
        entries: list[tuple[str, Path]] = []

        if mode in ("all", "recording"):
            entries.extend(self._collect(self._ctx.recording_dir, "Recording", _VIDEO_SUFFIXES))
        if mode in ("all", "snapshot"):
            entries.extend(self._collect(self._ctx.snapshot_dir, "Snapshot", _IMAGE_SUFFIXES))

        entries.sort(key=lambda item: item[1].stat().st_mtime if item[1].exists() else 0, reverse=True)
        self._entries = entries

        self._table.setRowCount(len(entries))
        for index, (kind, path) in enumerate(entries):
            try:
                stat = path.stat()
                size = _human_size(stat.st_size)
                modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                size, modified = "-", "-"
            for column, value in enumerate((kind, path.name, size, modified)):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setForeground(QColor(theme.TEXT if column == 1 else theme.TEXT_MUTED))
                item.setToolTip(str(path))
                self._table.setItem(index, column, item)

        self._stack.setCurrentWidget(self._table if entries else self._empty)
        self._count.setText(f"{len(entries)} file{'s' if len(entries) != 1 else ''}")

    @staticmethod
    def _collect(folder: Path, kind: str, suffixes: set[str]) -> list[tuple[str, Path]]:
        if not folder.exists():
            return []
        found: list[tuple[str, Path]] = []
        try:
            for path in folder.rglob("*"):
                if path.is_file() and path.suffix.lower() in suffixes:
                    found.append((kind, path))
                if len(found) >= 600:
                    break
        except OSError:
            return found
        return found

    # -- actions -----------------------------------------------------------
    def _selected_paths(self) -> list[Path]:
        paths: list[Path] = []
        model = self._table.selectionModel()
        if model is None:
            return paths
        for index in model.selectedRows():
            item = self._table.item(index.row(), 0)
            if item is not None:
                value = item.data(Qt.ItemDataRole.UserRole)
                if value:
                    paths.append(Path(str(value)))
        return paths

    def _open_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            self._ctx.notify("Select a file first.", "warning")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[0]))):
            self._ctx.notify(f"No application is associated with {paths[0].name}.", "error")

    def _open_folder(self) -> None:
        folder = (
            self._ctx.recording_dir
            if str(self._filter.currentData()) == "recording"
            else self._ctx.snapshot_dir
        )
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _delete_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            self._ctx.notify("Select one or more files to delete.", "warning")
            return

        allowed_roots = [self._ctx.recording_dir.resolve(), self._ctx.snapshot_dir.resolve()]
        safe: list[Path] = []
        for path in paths:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if any(resolved.is_relative_to(root) for root in allowed_roots):
                safe.append(resolved)

        if not safe:
            self._ctx.notify("Those files are outside the application data folders.", "error")
            return

        answer = QMessageBox.question(
            self,
            "Delete files",
            f"Delete {len(safe)} file(s) from disk?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        removed = 0
        failures = 0
        for path in safe:
            try:
                path.unlink()
                removed += 1
            except OSError:
                failures += 1
        self.refresh()
        if failures:
            self._ctx.notify(f"Deleted {removed} file(s); {failures} could not be removed.", "warning")
        else:
            self._ctx.notify(f"Deleted {removed} file(s).", "success")
