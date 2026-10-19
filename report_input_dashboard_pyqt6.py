"""Standalone PyQt6 launcher for the existing report input dashboard.

This entry point keeps report_input_dashboard.py unchanged while allowing the
Qt dashboard to be launched independently.
"""

import sys

from PyQt6.QtWidgets import QApplication

from report_input_dashboard import HAS_QT_FRONTEND, QT_IMPORT_ERROR, QtReportDashboard, install_qt_exception_hook


def main() -> int:
    if not HAS_QT_FRONTEND:
        print("PyQt6/qfluentwidgets is not available in this interpreter.")
        print(f"Import error: {QT_IMPORT_ERROR}")
        return 1

    app = QApplication(sys.argv)
    install_qt_exception_hook()
    app.setStyle("Fusion")
    window = QtReportDashboard()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
