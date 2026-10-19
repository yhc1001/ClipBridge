from __future__ import annotations

import sys
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from clipbridge.config import ConfigStore, set_autostart
from clipbridge.ui import Window
from clipbridge.instance import InstanceLock


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("ClipBridge")
    application.setQuitOnLastWindowClosed(False)
    smoke = "--smoke-test" in sys.argv
    instance = InstanceLock(os.environ.get("CLIPBRIDGE_SMOKE_INSTANCE") if smoke else None)
    if not instance.acquired:
        QMessageBox.information(None, "ClipBridge", "이미 실행 중입니다. 작업 표시줄의 트레이 아이콘에서 설정을 여세요.")
        instance.close()
        return 0
    window = None
    try:
        store = ConfigStore(Path(os.environ["CLIPBRIDGE_TEST_DATA"]) if smoke and os.environ.get("CLIPBRIDGE_TEST_DATA") else None)
        config = store.load()
        if config.autostart:
            set_autostart(True)
        window = Window(store, config)
        application.aboutToQuit.connect(window.quit)
        if "--background" not in sys.argv or (config.role == "server" and not config.peer_ip):
            window.show()
        # Used for build smoke tests; does not change settings or enable a connection.
        if "--smoke-test" in sys.argv:
            duration = 1800
            for argument in sys.argv:
                if argument.startswith("--smoke-seconds="):
                    duration = max(1, min(60, int(argument.split("=", 1)[1]))) * 1000
            QTimer.singleShot(duration, window.quit)
        return application.exec()
    except Exception as error:
        if window:
            window.quit()
        if smoke and os.environ.get("CLIPBRIDGE_STARTUP_DIAGNOSTIC"):
            import traceback
            Path(os.environ["CLIPBRIDGE_STARTUP_DIAGNOSTIC"]).write_text(traceback.format_exc(), encoding="utf-8")
            return 1
        QMessageBox.critical(None, "ClipBridge 시작 오류", "설정 또는 Windows 기능을 초기화하지 못했습니다.\n오류 종류: " + type(error).__name__ + "\nREADME의 문제 해결 안내를 확인하세요.")
        return 1
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
