"""Keep startup failures readable even when a packaged dependency cannot import."""
import ctypes
import os
import sys


if __name__ == "__main__":
    try:
        from main import main
        raise SystemExit(main())
    except Exception as error:
        # Opt-in developer smoke tests only. No runtime clipboard/data logging.
        diagnostic = os.environ.get("CLIPBRIDGE_STARTUP_DIAGNOSTIC")
        if diagnostic:
            import traceback
            with open(diagnostic, "w", encoding="utf-8") as stream:
                traceback.print_exc(file=stream)
        else:
            if sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(None, "ClipBridge를 시작하지 못했습니다.\n오류 종류: " + type(error).__name__ + "\nREADME의 문제 해결 안내를 확인하세요.", "ClipBridge 시작 오류", 0x10)
            else:
                from PySide6.QtWidgets import QApplication, QMessageBox
                application = QApplication.instance() or QApplication([])
                QMessageBox.critical(None, "ClipBridge 시작 오류", "필요한 구성 요소를 불러오지 못했습니다.\n오류 종류: " + type(error).__name__)
        sys.exit(1)
