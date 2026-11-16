"""Opt-in, short-lived Windows Han/Eng/Alt diagnostics. No network or file logging."""
import ctypes
from ctypes import wintypes
import sys
import time

WH_KEYBOARD_LL = 13
EVENT_NAMES = {0x100: "누름", 0x101: "뗌", 0x104: "누름", 0x105: "뗌"}
TARGET_VKS = {0x12, 0x15, 0x19, 0xA4, 0xA5}
TARGET_SCANS = {0x38, 0xF1, 0xF2}


def is_target(vk, scan):
    # Never display or store arbitrary text/keys, including IME PROCESSKEYs.
    # A scan-code check alone would risk logging keys on unusual keyboards.
    return vk in TARGET_VKS or (vk == 0xE5 and (scan & 0xFF) in TARGET_SCANS)


def event_text(vk, scan, flags, message, elapsed):
    origin = "프로그램에서 전달" if flags & 0x10 else "일반 입력"
    extended = "확장" if flags & 0x01 else "일반"
    return f"{elapsed:04.1f}초  {EVENT_NAMES[message]}  키={vk:02X} 위치={scan:02X} {extended} {origin}"


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows 전용 진단 도구입니다.")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD)
    user32.SetWindowsHookExW.restype = wintypes.HANDLE
    user32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.CallNextHookEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    class KeyboardEvent(ctypes.Structure):
        _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]

    class Window(QWidget):
        def __init__(self):
            super().__init__()
            self.hook = None
            self.callback = callback_type(self.on_key)
            self.started = 0
            self.count = 0
            self.events = []
            self.setWindowTitle("ClipBridge 한영키 확인")
            self.resize(720, 510)
            layout = QVBoxLayout(self)
            explanation = QLabel("노트북에서 실행하세요. 각 시험을 시작한 뒤 Moonlight 화면을 클릭하고 한영키와 오른쪽 Alt를 각각 3번 눌러 주세요.\n"
                                 "각 시험은 20초 후 끝납니다. 한영·Alt 키 신호만 화면에 표시하고 파일이나 인터넷에 저장하지 않습니다.")
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
            self.direct = QPushButton("1. 노트북 키보드로 시험 시작")
            self.remote = QPushButton("2. 메인 PC 키보드로 시험 시작")
            self.direct.clicked.connect(lambda: self.start("노트북 키보드"))
            self.remote.clicked.connect(lambda: self.start("메인 PC 키보드"))
            layout.addWidget(self.direct)
            layout.addWidget(self.remote)
            self.status = QLabel("준비됨")
            layout.addWidget(self.status)
            self.output = QPlainTextEdit()
            self.output.setReadOnly(True)
            self.output.document().setMaximumBlockCount(100)
            layout.addWidget(self.output)
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.stop)

        def start(self, label):
            self.stop()
            self.started = time.monotonic()
            self.count = 0
            self.events = []
            self.output.appendPlainText("\n[" + label + "]")
            self.hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.callback, kernel32.GetModuleHandleW(None), 0)
            if not self.hook:
                self.status.setText("시작하지 못했습니다. 이 창을 닫고 다시 실행해 주세요.")
                return
            self.status.setText("20초 동안 확인 중… Moonlight를 클릭하고 한영키와 오른쪽 Alt를 각각 3번 눌러 주세요.")
            self.timer.start(20000)

        def on_key(self, code, message, pointer):
            if code >= 0 and message in EVENT_NAMES and self.count < 40:
                event = ctypes.cast(pointer, ctypes.POINTER(KeyboardEvent)).contents
                if is_target(event.vk, event.scan):
                    self.events.append((event.vk, event.scan, event.flags, message, time.monotonic() - self.started))
                    self.count += 1
            return user32.CallNextHookEx(self.hook, code, message, pointer)

        def stop(self):
            self.timer.stop()
            if self.hook:
                user32.UnhookWindowsHookEx(self.hook)
                self.hook = None
                for event in self.events:
                    self.output.appendPlainText(event_text(*event))
                self.events.clear()
                self.output.appendPlainText("시험 종료")
                self.status.setText("시험 종료. 두 결과가 보이도록 사진을 찍어 보내 주세요.")

        def closeEvent(self, event):
            self.stop()
            super().closeEvent(event)

    app = QApplication(sys.argv)
    window = Window()
    window.show()
    if "--smoke" in sys.argv:
        QTimer.singleShot(300, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
