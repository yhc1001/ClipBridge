from __future__ import annotations

import sys

import win32api
import win32event
import win32security
import win32con
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from clipbridge.config import ConfigStore
from clipbridge.ui import Window


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("ClipBridge")
    application.setQuitOnLastWindowClosed(False)
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
    finally:
        token.Close()
    # One instance per Windows user across sessions sharing that user's AppData.
    mutex = win32event.CreateMutex(None, False, "Global\\ClipBridge-v1-" + sid)
    if win32api.GetLastError() == 183:
        QMessageBox.information(None, "ClipBridge", "이미 실행 중입니다. 작업 표시줄의 트레이 아이콘에서 설정을 여세요.")
        win32api.CloseHandle(mutex)
        return 0
    window = None
    try:
        store = ConfigStore()
        config = store.load()
        window = Window(store, config)
        application.aboutToQuit.connect(window.quit)
        if "--background" not in sys.argv or not config.peer_ip:
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
        QMessageBox.critical(None, "ClipBridge 시작 오류", "설정 또는 Windows 기능을 초기화하지 못했습니다.\n오류 종류: " + type(error).__name__ + "\nREADME의 문제 해결 안내를 확인하세요.")
        return 1
    finally:
        win32api.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
