from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QDialog,
    QComboBox, QLineEdit, QDialogButtonBox, QFormLayout
)

from src.models import BoundaryCondition, FaceLabel, SimulationType

_SUPPORTS = ["Fixed", "Frictionless", "Displacement", "Symmetric"]
_LOADS    = ["Force", "Pressure", "Remote Force", "Moment"]
_THERMAL  = ["Temperature", "Convection", "Heat Flux"]


class _BCDialog(QDialog):

    def __init__(self, bc_types: list[str], face_labels: list[FaceLabel], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Boundary Condition")
        form = QFormLayout(self)
        self._type = QComboBox()
        self._type.addItems(bc_types)
        self._target = QComboBox()
        self._target.setEditable(True)
        if face_labels:
            for fl in face_labels:
                self._target.addItem(fl.name)
        else:
            self._target.lineEdit().setPlaceholderText("e.g. Top face, Bottom face")
        self._mag = QLineEdit()
        self._mag.setPlaceholderText("Leave blank for Fixed / Frictionless")
        self._dir = QComboBox()
        self._dir.addItems(["", "X", "Y", "Z", "Normal"])
        self._unit = QComboBox()
        self._unit.addItems(["N", "Pa", "N·m", "°C", "W/m²"])
        form.addRow("Type:", self._type)
        form.addRow("Target face/edge:", self._target)
        form.addRow("Magnitude:", self._mag)
        form.addRow("Direction:", self._dir)
        form.addRow("Unit:", self._unit)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_bc(self) -> BoundaryCondition:
        mag_text = self._mag.text().strip()
        return BoundaryCondition(
            bc_type=self._type.currentText(),
            target=self._target.currentText(),
            magnitude=float(mag_text) if mag_text else None,
            direction=self._dir.currentText() or None,
            unit=self._unit.currentText(),
        )


class BCsPage(QWizardPage):

    def __init__(self):
        super().__init__()
        self.setTitle("Step 4 — Boundary Conditions")
        self.setSubTitle("Add supports and loads. Pick a face from the auto-detected list, or type a custom name.")
        self._bcs: list[BoundaryCondition] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._sup_list = self._make_section(layout, "Supports", _SUPPORTS)
        self._load_list = self._make_section(layout, "Loads", None)
        self._hint = QLabel("")
        self._hint.setStyleSheet("color:#0066cc;font-style:italic")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

    def _make_section(self, parent_layout, title: str, bc_types):
        parent_layout.addWidget(QLabel(f"<b>{title}</b>"))
        lw = QListWidget()
        parent_layout.addWidget(lw)
        row = QHBoxLayout()
        add = QPushButton(f"+ Add {title[:-1]}")
        rm = QPushButton("Remove")
        add.clicked.connect(lambda _, t=title, lw=lw, bct=bc_types: self._add(t, lw, bct))
        rm.clicked.connect(
            lambda _, lw=lw: lw.takeItem(lw.currentRow()) if lw.currentRow() >= 0 else None
        )
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch()
        parent_layout.addLayout(row)
        return lw

    def _load_types(self):
        sim = self.wizard().property("sim_type")
        return _LOADS + (_THERMAL if sim == SimulationType.THERMAL_STRUCTURAL else [])

    def initializePage(self):
        features = self.wizard().property("geometry_features")
        hints = []
        if features and features.symmetry_planes:
            hints.append(
                f"Symmetry detected ({', '.join(features.symmetry_planes)}) — consider a Symmetric support."
            )
        if features and features.body_count > 1:
            hints.append("Multiple bodies — define contact regions in Mechanical before solving.")
        self._hint.setText("\n".join(hints))

    def _add(self, section: str, lw: QListWidget, bc_types):
        types = bc_types if bc_types is not None else self._load_types()
        features = self.wizard().property("geometry_features")
        face_labels = features.faces if features and features.faces else []
        dlg = _BCDialog(types, face_labels, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        bc = dlg.get_bc()
        self._bcs.append(bc)
        label = f"{bc.bc_type} → {bc.target}"
        if bc.magnitude is not None:
            label += f"  [{bc.magnitude} {bc.unit}{' ' + bc.direction if bc.direction else ''}]"
        lw.addItem(QListWidgetItem(label))
        self.wizard().setProperty("boundary_conditions", self._bcs)
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return len(self._bcs) > 0
