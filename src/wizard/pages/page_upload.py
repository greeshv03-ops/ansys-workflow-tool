import os

from PyQt6.QtWidgets import (
    QWizardPage, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QProgressBar, QFrame, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from src.geometry.analyzer import GeometryAnalyzer
from src.models import GeometryFeatures
from src.wizard.viewer import GeometryViewer


class _AnalyzerThread(QThread):
    done = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        try:
            features, named_solids = GeometryAnalyzer.analyze_with_solids(self._path)
            self.done.emit(features, named_solids)
        except Exception as e:
            self.failed.emit(str(e))


class _DropZone(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(60)
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

        top = QHBoxLayout()
        self._drop_zone = _DropZone()
        self._drop_zone.file_dropped.connect(self._load)
        top.addWidget(self._drop_zone, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        top.addWidget(browse)
        layout.addLayout(top)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.hide()
        layout.addWidget(self._progress)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self._viewer = GeometryViewer()
        self._viewer.setMinimumHeight(360)
        splitter.addWidget(self._viewer)

        self._info = QLabel("")
        self._info.setWordWrap(True)
        self._info.setMinimumHeight(48)
        splitter.addWidget(self._info)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

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

    def _on_done(self, features: GeometryFeatures, named_solids):
        self._features = features
        self._progress.hide()
        self.wizard().setProperty("geometry_features", features)
        self.wizard().setProperty("geometry_named_solids", named_solids)
        self._viewer.set_geometry(named_solids)

        b = features.bbox
        header = f"Bbox: {b[0]:.1f} × {b[1]:.1f} × {b[2]:.1f} mm  |  Bodies: {features.body_count}"
        if features.body_count > 3 and not features.faces:
            self._info.setText(
                header
                + "\nMulti-body assembly — detailed feature analysis skipped for speed."
            )
        else:
            tags = []
            if features.thin_walls:
                tags.append("Thin walls")
            if features.holes:
                tags.append(f"{len(features.holes)} hole(s)")
            if features.symmetry_planes:
                tags.append(f"Symmetry: {', '.join(features.symmetry_planes)}")
            if features.sharp_edges:
                tags.append("Sharp edges")
            self._info.setText(
                header + "\n"
                + ("  |  ".join(tags) if tags else "No special features detected")
            )
        self.completeChanged.emit()

    def _on_error(self, msg: str):
        self._progress.hide()
        self._info.setText(f"Error: {msg}\nRe-export the file from your CAD tool and try again.")

    def isComplete(self) -> bool:
        return self._features is not None
