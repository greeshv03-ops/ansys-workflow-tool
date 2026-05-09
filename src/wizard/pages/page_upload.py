import os

from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from src.geometry.analyzer import GeometryAnalyzer
from src.models import GeometryFeatures


class _AnalyzerThread(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        try:
            self.done.emit(GeometryAnalyzer.analyze(self._path))
        except Exception as e:
            self.failed.emit(str(e))


class _DropZone(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(100)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        self._lbl = QLabel("Drop CAD file here")
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl)

    def set_filename(self, path: str):
        self._lbl.setText(f"✓  {os.path.basename(path)}")

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        urls = e.mimeData().urls()
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())


class UploadPage(QWizardPage):

    def __init__(self):
        super().__init__()
        self.setTitle("Step 1 — Upload Geometry")
        self.setSubTitle("Drop your CAD file below or click Browse.  Supported: .step  .stp  .iges  .igs")
        self._features: GeometryFeatures | None = None
        self._thread: _AnalyzerThread | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._drop_zone = _DropZone()
        self._drop_zone.file_dropped.connect(self._load)
        layout.addWidget(self._drop_zone)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignRight)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._info = QLabel("")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select CAD File", "",
            "CAD Files (*.step *.stp *.iges *.igs);;All Files (*)"
        )
        if path:
            self._load(path)

    def _load(self, path: str):
        self._features = None
        self._drop_zone.set_filename(path)
        self._progress.show()
        self._info.setText("Analyzing geometry…")
        self.wizard().setProperty("geometry_path", path)
        self._thread = _AnalyzerThread(path)
        self._thread.done.connect(self._on_done)
        self._thread.failed.connect(self._on_error)
        self._thread.start()

    def _on_done(self, features: GeometryFeatures):
        self._features = features
        self._progress.hide()
        self.wizard().setProperty("geometry_features", features)
        tags = []
        if features.thin_walls:
            tags.append("Thin walls")
        if features.holes:
            tags.append(f"{len(features.holes)} hole(s)")
        if features.symmetry_planes:
            tags.append(f"Symmetry: {', '.join(features.symmetry_planes)}")
        if features.sharp_edges:
            tags.append("Sharp edges")
        b = features.bbox
        self._info.setText(
            f"Bbox: {b[0]:.1f} × {b[1]:.1f} × {b[2]:.1f} mm  |  Bodies: {features.body_count}\n"
            + ("  |  ".join(tags) if tags else "No special features detected")
        )
        self.completeChanged.emit()

    def _on_error(self, msg: str):
        self._progress.hide()
        self._info.setText(f"Error: {msg}\nRe-export the file from your CAD tool and try again.")

    def isComplete(self) -> bool:
        return self._features is not None
