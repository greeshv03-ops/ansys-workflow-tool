import sys

from PyQt6.QtWidgets import QApplication

from src.wizard.main_wizard import ANSYSWizard


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ANSYS Simulation Setup Wizard")
    wizard = ANSYSWizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
