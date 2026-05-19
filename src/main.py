import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication

from src.wizard.main_wizard import ANSYSWizard


def _silence_vtk_shutdown_warnings():
    # VTK's vtkWin32OpenGLRenderWindow destructor calls wglMakeCurrent after
    # Qt has already torn down the underlying HDC. Each failure goes through
    # vtkWin32OpenGLRenderWindow.cxx:255 with a DWORD error code that
    # FormatMessageW mis-formats as garbled Unicode. The errors are
    # cosmetic — there is nothing left to render — but they flood stderr.
    # Silencing only during shutdown keeps real runtime warnings visible.
    import vtk
    vtk.vtkObject.GlobalWarningDisplayOff()


def main():
    # VTK's QtInteractor needs an OpenGL 3.2 Core surface negotiated before
    # QApplication exists; otherwise wglMakeCurrent fails with
    # ERROR_INCORRECT_PIXEL_TYPE on the embedded render windows.
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("ANSYS Simulation Setup Wizard")
    app.aboutToQuit.connect(_silence_vtk_shutdown_warnings)
    wizard = ANSYSWizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
