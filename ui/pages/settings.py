"""Settings page: detection, event rules, regions, storage and privacy."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.defaults import COCO_CLASSES, DEFAULT_ENABLED_CLASSES
from detection.model_manager import SUGGESTED_MODELS
from events.regions import regions_from_config, regions_to_config
from ui import theme
from ui.context import AppContext
from ui.dialogs.region_editor import RegionEditorDialog
from ui.widgets.common import Card, h_line


class SettingsPage(QWidget):
    settings_changed = Signal(dict)

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._frame_provider: Callable[[], QImage | None] | None = None
        self._class_boxes: dict[str, QCheckBox] = {}
        self._pending_regions: list[dict] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        content = QVBoxLayout(container)
        content.setContentsMargins(0, 0, 8, 0)
        content.setSpacing(14)

        content.addWidget(self._build_model_card())
        content.addWidget(self._build_classes_card())
        content.addWidget(self._build_events_card())
        content.addWidget(self._build_hazard_card())
        content.addWidget(self._build_storage_card())
        content.addWidget(self._build_privacy_card())
        content.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        # -- action bar ----------------------------------------------------
        bar = QFrame()
        bar.setObjectName("toolbar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(9)
        self._status = QLabel("Changes are applied when you press Save.")
        self._status.setObjectName("dim")
        bar_layout.addWidget(self._status, 1)
        reset_btn = QPushButton("Restore defaults")
        reset_btn.setObjectName("ghost")
        reset_btn.clicked.connect(self._restore_defaults)
        bar_layout.addWidget(reset_btn)
        self._save_btn = QPushButton("Save settings")
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self.save)
        bar_layout.addWidget(self._save_btn)
        outer.addWidget(bar)

        self.reload()

    # -- builders ----------------------------------------------------------
    def _build_model_card(self) -> Card:
        card = Card()
        title = QLabel("Detection")
        title.setObjectName("sectionTitle")
        card.add(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        for name, description in SUGGESTED_MODELS:
            self._model_combo.addItem(name, name)
            self._model_combo.setItemData(self._model_combo.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        self._model_combo.setMinimumWidth(280)
        form.addRow("Checkpoint", self._model_combo)

        self._device_combo = QComboBox()
        self._device_combo.setEditable(True)
        self._device_combo.addItems(["cpu", "cuda:0"])
        self._device_combo.setMinimumWidth(160)
        form.addRow("Device", self._device_combo)

        self._imgsz_combo = QComboBox()
        for size in (416, 512, 640, 800, 960, 1280):
            self._imgsz_combo.addItem(f"{size} px", size)
        self._imgsz_combo.setMinimumWidth(160)
        form.addRow("Inference size", self._imgsz_combo)

        self._max_det = QSpinBox()
        self._max_det.setRange(1, 300)
        self._max_det.setMinimumWidth(120)
        form.addRow("Max detections", self._max_det)

        confidence_row, self._confidence, self._confidence_label = self._slider(5, 95, 35, "%")
        form.addRow("Confidence threshold", confidence_row)

        iou_row, self._iou, self._iou_label = self._slider(5, 95, 45, "%")
        form.addRow("NMS IoU", iou_row)

        toggles = QHBoxLayout()
        toggles.setSpacing(18)
        self._detection_enabled = QCheckBox("Run detection")
        self._tracking_enabled = QCheckBox("Assign tracking IDs (ByteTrack)")
        self._trails_enabled = QCheckBox("Draw tracking trails")
        toggles.addWidget(self._detection_enabled)
        toggles.addWidget(self._tracking_enabled)
        toggles.addWidget(self._trails_enabled)
        toggles.addStretch(1)
        form.addRow("", self._wrap(toggles))

        note = QLabel(
            "Lower confidence finds more objects but increases false positives. "
            "Inference size is the biggest performance lever on CPU: 416 is fast, "
            "640 is balanced, 1280 is slow but better for distant objects."
        )
        note.setObjectName("dim")
        note.setWordWrap(True)
        form.addRow("", note)

        card.body().addLayout(form)
        return card

    def _build_classes_card(self) -> Card:
        card = Card()
        header = QHBoxLayout()
        title = QLabel("Object classes")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        common_btn = QPushButton("Common set")
        common_btn.setObjectName("ghost")
        common_btn.clicked.connect(self._select_common_classes)
        header.addWidget(common_btn)
        all_btn = QPushButton("Select all")
        all_btn.setObjectName("ghost")
        all_btn.clicked.connect(lambda: self._set_all_classes(True))
        header.addWidget(all_btn)
        none_btn = QPushButton("Clear")
        none_btn.setObjectName("ghost")
        none_btn.clicked.connect(lambda: self._set_all_classes(False))
        header.addWidget(none_btn)
        card.body().addLayout(header)

        hint = QLabel(
            "Only checked classes are passed to the tracker and the event engine. "
            "Names match the labels of the loaded checkpoint."
        )
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        card.add(hint)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(2)
        columns = 4
        for index, name in enumerate(COCO_CLASSES):
            box = QCheckBox(name)
            self._class_boxes[name] = box
            grid.addWidget(box, index // columns, index % columns)
        card.add(grid_widget)
        return card

    def _build_events_card(self) -> Card:
        card = Card()
        title = QLabel("Event rules")
        title.setObjectName("sectionTitle")
        card.add(title)

        hint = QLabel(
            "A plain detection event fires when an object of the chosen class is seen. "
            "Region events only fire for polygons you have drawn, and are labelled "
            "separately in the event history."
        )
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        card.add(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)

        row = QHBoxLayout()
        row.setSpacing(18)
        self._person_events = QCheckBox("Person detected")
        self._vehicle_events = QCheckBox("Vehicle detected")
        row.addWidget(self._person_events)
        row.addWidget(self._vehicle_events)
        row.addStretch(1)
        form.addRow("Detection events", self._wrap(row))

        row2 = QHBoxLayout()
        row2.setSpacing(18)
        self._region_intrusion = QCheckBox("Object enters a region")
        self._region_loitering = QCheckBox("Object loiters in a region")
        row2.addWidget(self._region_intrusion)
        row2.addWidget(self._region_loitering)
        row2.addStretch(1)
        form.addRow("Region events", self._wrap(row2))

        self._cooldown = QDoubleSpinBox()
        self._cooldown.setRange(0.0, 3600.0)
        self._cooldown.setSingleStep(1.0)
        self._cooldown.setSuffix(" s")
        self._cooldown.setMinimumWidth(120)
        form.addRow("Event cooldown", self._cooldown)

        self._loiter = QDoubleSpinBox()
        self._loiter.setRange(1.0, 3600.0)
        self._loiter.setSingleStep(1.0)
        self._loiter.setSuffix(" s")
        self._loiter.setMinimumWidth(120)
        form.addRow("Loitering threshold", self._loiter)

        self._snapshots = QCheckBox("Save an evidence snapshot for every event")
        form.addRow("Evidence", self._snapshots)

        self._max_events = QSpinBox()
        self._max_events.setRange(100, 500000)
        self._max_events.setSingleStep(1000)
        self._max_events.setMinimumWidth(140)
        form.addRow("Keep newest events", self._max_events)

        card.body().addLayout(form)

        card.add(h_line())

        region_row = QHBoxLayout()
        self._region_summary = QLabel("No regions configured")
        self._region_summary.setObjectName("muted")
        region_row.addWidget(self._region_summary, 1)
        edit_btn = QPushButton("Edit regions…")
        edit_btn.clicked.connect(self._edit_regions)
        region_row.addWidget(edit_btn)
        card.body().addLayout(region_row)

        region_note = QLabel(
            "Regions are polygons drawn on the video frame. Use them for driveways, "
            "doorways or restricted areas."
        )
        region_note.setObjectName("dim")
        region_note.setWordWrap(True)
        card.add(region_note)
        return card

    def _build_hazard_card(self) -> Card:
        card = Card()
        title = QLabel("Safety alerts")
        title.setObjectName("sectionTitle")
        card.add(title)

        note = QLabel(
            "These are heuristics built on the object detector, not a weapon or "
            "violence classifier. They warn when a hazard object sits next to a "
            "person, or when two people overlap and move together for a while. "
            "Expect false positives (a chef with a knife, people hugging) and false "
            "negatives. COCO has no firearm class, so guns are only detected with a "
            "custom checkpoint whose class names you add to the hazard list."
        )
        note.setObjectName("dim")
        note.setWordWrap(True)
        card.add(note)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)

        self._hazard_enabled = QCheckBox("Raise safety alerts")
        form.addRow("Safety alerts", self._hazard_enabled)

        self._hazard_classes = QLineEdit()
        self._hazard_classes.setPlaceholderText("knife, baseball bat, scissors")
        self._hazard_classes.setMinimumWidth(320)
        form.addRow("Hazard classes", self._hazard_classes)

        self._hazard_proximity = QCheckBox("Only when a person is next to the object")
        form.addRow("Proximity", self._hazard_proximity)

        self._hazard_factor = QDoubleSpinBox()
        self._hazard_factor.setRange(0.20, 2.00)
        self._hazard_factor.setSingleStep(0.05)
        self._hazard_factor.setDecimals(2)
        self._hazard_factor.setMinimumWidth(110)
        form.addRow("Proximity range", self._hazard_factor)

        self._altercation_enabled = QCheckBox(
            "Detect possible altercations between people"
        )
        form.addRow("Altercation", self._altercation_enabled)

        self._altercation_overlap = QDoubleSpinBox()
        self._altercation_overlap.setRange(0.05, 0.90)
        self._altercation_overlap.setSingleStep(0.01)
        self._altercation_overlap.setDecimals(2)
        self._altercation_overlap.setMinimumWidth(110)
        form.addRow("Minimum box overlap", self._altercation_overlap)

        self._altercation_seconds = QDoubleSpinBox()
        self._altercation_seconds.setRange(0.5, 30.0)
        self._altercation_seconds.setSingleStep(0.5)
        self._altercation_seconds.setSuffix(" s")
        self._altercation_seconds.setMinimumWidth(110)
        form.addRow("Sustained for", self._altercation_seconds)

        self._hazard_cooldown = QDoubleSpinBox()
        self._hazard_cooldown.setRange(5.0, 600.0)
        self._hazard_cooldown.setSingleStep(5.0)
        self._hazard_cooldown.setSuffix(" s")
        self._hazard_cooldown.setMinimumWidth(110)
        form.addRow("Alert cooldown", self._hazard_cooldown)

        form.addRow(h_line())

        self._violence_enabled = QCheckBox("Run the violence model")
        form.addRow("Violence model", self._violence_enabled)

        self._violence_model = QLineEdit()
        self._violence_model.setPlaceholderText("yolo_small_weights.pt")
        self._violence_model.setMinimumWidth(320)
        form.addRow("Weights file", self._violence_model)

        self._violence_conf = QDoubleSpinBox()
        self._violence_conf.setRange(0.10, 0.95)
        self._violence_conf.setSingleStep(0.05)
        self._violence_conf.setDecimals(2)
        self._violence_conf.setMinimumWidth(110)
        form.addRow("Confidence", self._violence_conf)

        self._violence_stride = QSpinBox()
        self._violence_stride.setRange(1, 10)
        self._violence_stride.setMinimumWidth(110)
        self._violence_stride.setToolTip(
            "Running a second model costs a second inference pass. 2 halves that cost."
        )
        form.addRow("Run every N frames", self._violence_stride)

        self._violence_cooldown = QDoubleSpinBox()
        self._violence_cooldown.setRange(5.0, 600.0)
        self._violence_cooldown.setSingleStep(5.0)
        self._violence_cooldown.setSuffix(" s")
        self._violence_cooldown.setMinimumWidth(110)
        form.addRow("Alarm cooldown", self._violence_cooldown)

        violence_note = QLabel(
            "The bundled yolo_small_weights.pt is a YOLOv8 detector with two "
            "classes: non_violence and violence. Only 'violence' raises an alarm. "
            "If the weights file is missing, violence detection switches itself off "
            "and the rest of the application keeps working."
        )
        violence_note.setObjectName("dim")
        violence_note.setWordWrap(True)
        form.addRow(violence_note)

        card.body().addLayout(form)
        return card

    def _build_storage_card(self) -> Card:
        card = Card()
        title = QLabel("Storage")
        title.setObjectName("sectionTitle")
        card.add(title)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)

        self._snapshot_dir = QLineEdit(str(self._ctx.snapshot_dir))
        self._snapshot_dir.setReadOnly(True)
        form.addRow("Snapshots", self._snapshot_dir)

        self._recording_dir = QLineEdit(str(self._ctx.recording_dir))
        self._recording_dir.setReadOnly(True)
        form.addRow("Recordings", self._recording_dir)

        self._db_path = QLineEdit(str(self._ctx.db.path))
        self._db_path.setReadOnly(True)
        form.addRow("Database", self._db_path)

        card.body().addLayout(form)
        note = QLabel(
            "These folders are created automatically. Recordings and snapshots are "
            "written only when you press the corresponding button or enable evidence "
            "snapshots."
        )
        note.setObjectName("dim")
        note.setWordWrap(True)
        card.add(note)
        return card

    def _build_privacy_card(self) -> Card:
        card = Card()
        title = QLabel("Privacy")
        title.setObjectName("sectionTitle")
        card.add(title)
        text = QLabel(
            "• All processing happens on this computer. No frame, snapshot or event is "
            "uploaded anywhere.\n"
            "• The only network access is the one-time download of the YOLO weights and, "
            "if you use one, the connection to your own IP camera.\n"
            "• The system does not perform facial recognition and does not identify "
            "people. Tracking IDs are temporary counters that reset when the source "
            "changes.\n"
            "• Motion and object detection can produce false positives, especially at "
            "night, in poor light, or with reflective surfaces.\n"
            "• Snapshots and recordings are explicit actions; nothing is captured "
            "silently."
        )
        text.setWordWrap(True)
        text.setObjectName("muted")
        card.add(text)
        return card

    # -- small helpers -----------------------------------------------------
    @staticmethod
    def _wrap(layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return widget

    def _slider(self, minimum: int, maximum: int, value: int, suffix: str):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setMinimumWidth(220)
        label = QLabel(f"{value}{suffix}")
        label.setObjectName("mono")
        label.setMinimumWidth(48)
        slider.valueChanged.connect(lambda v: label.setText(f"{v}{suffix}"))
        layout.addWidget(slider, 1)
        layout.addWidget(label)
        return container, slider, label

    # -- class selection ---------------------------------------------------
    def _set_all_classes(self, checked: bool) -> None:
        for box in self._class_boxes.values():
            box.setChecked(checked)

    def _select_common_classes(self) -> None:
        for name, box in self._class_boxes.items():
            box.setChecked(name in DEFAULT_ENABLED_CLASSES)

    # -- regions -----------------------------------------------------------
    def set_frame_provider(self, provider: Callable[[], QImage | None]) -> None:
        self._frame_provider = provider

    def _edit_regions(self) -> None:
        current = regions_from_config(self._ctx.config.get("events.regions", []))
        frame = self._frame_provider() if self._frame_provider else None
        dialog = RegionEditorDialog(current, frame, self)
        if dialog.exec() == RegionEditorDialog.DialogCode.Accepted:
            self._pending_regions = regions_to_config(dialog.regions())
            self._region_summary.setText(self._describe_regions(dialog.regions()))
            self._status.setText("Region changes are pending - press Save settings.")
        else:
            self._pending_regions = regions_to_config(current)

    @staticmethod
    def _describe_regions(regions: list) -> str:
        if not regions:
            return "No regions configured"
        active = sum(1 for region in regions if getattr(region, "enabled", True))
        names = ", ".join(region.name for region in regions[:4])
        if len(regions) > 4:
            names += f" (+{len(regions) - 4} more)"
        return f"{len(regions)} region(s), {active} active: {names}"

    # -- load / save -------------------------------------------------------
    def reload(self) -> None:
        config = self._ctx.config
        detection = config.section("detection")
        events = config.section("events")

        model = str(detection.get("model", "yolov8n.pt"))
        index = self._model_combo.findData(model)
        if index >= 0:
            self._model_combo.setCurrentIndex(index)
        else:
            self._model_combo.setEditText(model)

        self._device_combo.setCurrentText(str(detection.get("device", "cpu")))

        imgsz = int(detection.get("imgsz", 640))
        idx = self._imgsz_combo.findData(imgsz)
        if idx >= 0:
            self._imgsz_combo.setCurrentIndex(idx)
        else:
            self._imgsz_combo.setCurrentIndex(2)

        self._max_det.setValue(int(detection.get("max_detections", 100)))
        self._confidence.setValue(int(round(float(detection.get("confidence", 0.35)) * 100)))
        self._iou.setValue(int(round(float(detection.get("iou", 0.45)) * 100)))
        self._detection_enabled.setChecked(bool(detection.get("enabled", True)))
        self._tracking_enabled.setChecked(bool(detection.get("tracking_enabled", True)))
        self._trails_enabled.setChecked(bool(detection.get("show_trails", True)))

        enabled = set(detection.get("enabled_classes", []) or [])
        for name, box in self._class_boxes.items():
            box.setChecked(name in enabled)

        self._person_events.setChecked(bool(events.get("person_detected", True)))
        self._vehicle_events.setChecked(bool(events.get("vehicle_detected", True)))
        self._region_intrusion.setChecked(bool(events.get("region_intrusion", False)))
        self._region_loitering.setChecked(bool(events.get("region_loitering", False)))
        self._cooldown.setValue(float(events.get("cooldown_s", 15.0)))
        self._loiter.setValue(float(events.get("loiter_seconds", 8.0)))
        self._snapshots.setChecked(bool(events.get("save_snapshots", False)))
        self._max_events.setValue(int(events.get("max_stored_events", 20000)))

        hazards = events.get("hazards", {}) or {}
        self._hazard_enabled.setChecked(bool(hazards.get("enabled", True)))
        self._hazard_classes.setText(", ".join(hazards.get("classes", []) or []))
        self._hazard_proximity.setChecked(
            bool(hazards.get("require_person_proximity", True))
        )
        self._hazard_factor.setValue(float(hazards.get("proximity_factor", 0.75)))
        self._altercation_enabled.setChecked(bool(hazards.get("altercation_enabled", True)))
        self._altercation_overlap.setValue(float(hazards.get("altercation_overlap", 0.22)))
        self._altercation_seconds.setValue(float(hazards.get("altercation_min_seconds", 1.2)))
        self._hazard_cooldown.setValue(float(hazards.get("cooldown_s", 30.0)))

        safety = self._ctx.config.section("safety_model")
        self._violence_enabled.setChecked(bool(safety.get("enabled", True)))
        self._violence_model.setText(str(safety.get("model", "yolo_small_weights.pt")))
        self._violence_conf.setValue(float(safety.get("confidence", 0.45)))
        self._violence_stride.setValue(int(safety.get("run_every_n_frames", 2)))
        self._violence_cooldown.setValue(float(safety.get("cooldown_s", 20.0)))

        regions = regions_from_config(events.get("regions", []))
        self._pending_regions = regions_to_config(regions)
        self._region_summary.setText(self._describe_regions(regions))
        self._status.setText("Changes are applied when you press Save.")

    def save(self) -> None:
        model_name = self._model_combo.currentData() or self._model_combo.currentText().strip()
        enabled_classes = [name for name, box in self._class_boxes.items() if box.isChecked()]
        if not enabled_classes:
            answer = QMessageBox.question(
                self,
                "No classes enabled",
                "Every object class is unchecked, so nothing will be detected.\n\n"
                "Save anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        safety_update = dict(self._ctx.config.section("safety_model") or {})
        safety_update.update({
            "enabled": bool(self._violence_enabled.isChecked()),
            "model": self._violence_model.text().strip() or "yolo_small_weights.pt",
            "confidence": round(float(self._violence_conf.value()), 2),
            "run_every_n_frames": int(self._violence_stride.value()),
            "cooldown_s": round(float(self._violence_cooldown.value()), 1),
        })

        updates = {
            "detection.model": str(model_name),
            "detection.device": self._device_combo.currentText().strip() or "cpu",
            "detection.imgsz": int(self._imgsz_combo.currentData() or 640),
            "detection.max_detections": int(self._max_det.value()),
            "detection.confidence": round(self._confidence.value() / 100.0, 3),
            "detection.iou": round(self._iou.value() / 100.0, 3),
            "detection.enabled": bool(self._detection_enabled.isChecked()),
            "detection.tracking_enabled": bool(self._tracking_enabled.isChecked()),
            "detection.show_trails": bool(self._trails_enabled.isChecked()),
            "detection.enabled_classes": enabled_classes,
            "events.person_detected": bool(self._person_events.isChecked()),
            "events.vehicle_detected": bool(self._vehicle_events.isChecked()),
            "events.region_intrusion": bool(self._region_intrusion.isChecked()),
            "events.region_loitering": bool(self._region_loitering.isChecked()),
            "events.cooldown_s": float(self._cooldown.value()),
            "events.loiter_seconds": float(self._loiter.value()),
            "events.save_snapshots": bool(self._snapshots.isChecked()),
            "events.max_stored_events": int(self._max_events.value()),
            "events.hazards": {
                "enabled": bool(self._hazard_enabled.isChecked()),
                "classes": [
                    part.strip()
                    for part in self._hazard_classes.text().split(",")
                    if part.strip()
                ],
                "require_person_proximity": bool(self._hazard_proximity.isChecked()),
                "proximity_factor": round(float(self._hazard_factor.value()), 2),
                "altercation_enabled": bool(self._altercation_enabled.isChecked()),
                "altercation_overlap": round(float(self._altercation_overlap.value()), 2),
                "altercation_min_seconds": round(float(self._altercation_seconds.value()), 2),
                "cooldown_s": round(float(self._hazard_cooldown.value()), 1),
            },
            "events.regions": self._pending_regions,
            "safety_model": safety_update,
        }
        try:
            self._ctx.config.update(updates)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        self._ctx.pipeline.apply_settings()
        self._status.setText("Saved. Detection settings are applied immediately.")
        self.settings_changed.emit(self._ctx.config.snapshot())
        self._ctx.notify("Settings saved.", "success")

    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restore defaults",
            "Reset every setting to its default value?\n\n"
            "Event history, recordings and snapshots are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._ctx.config.reset()
        self.reload()
        self._ctx.pipeline.apply_settings()
        self.settings_changed.emit(self._ctx.config.snapshot())
        self._ctx.notify("Defaults restored.", "success")

    def refresh(self) -> None:
        # Called when the page becomes visible; do not clobber unsaved edits.
        pass
