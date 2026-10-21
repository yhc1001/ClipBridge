"""Actual native input into a private SYSTEM/Admin-only desktop on Windows CI.

This never opens or accepts a UAC consent dialog, and refuses to run locally.
The previous input desktop is restored even when an assertion fails.
"""
import ctypes
import os
import struct
import threading
import time
import uuid

if os.environ.get("GITHUB_ACTIONS") != "true" or os.name != "nt":
    raise RuntimeError("Secure desktop probe is restricted to disposable Windows CI")

import win32api
import win32con
import win32gui
import win32security
import win32ts


class SecurityAttributes(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("descriptor", ctypes.c_void_p), ("inherit", ctypes.c_int)]


class Probe:
    def __init__(self):
        self.ready, self.key, self.done = threading.Event(), threading.Event(), threading.Event()
        self.cursor = None
        self.error = None
        self.thread = threading.Thread(target=self.run)

    def run(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.OpenInputDesktop.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        user.OpenInputDesktop.restype = ctypes.c_void_p
        user.CreateDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        user.CreateDesktopW.restype = ctypes.c_void_p
        for name in ("SwitchDesktop", "SetThreadDesktop", "CloseDesktop"):
            getattr(user, name).argtypes = [ctypes.c_void_p]
        previous = desktop = window = None
        try:
            previous = user.OpenInputDesktop(0, False, 0x1FF)
            if not previous:
                raise ctypes.WinError(ctypes.get_last_error())
            descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor("D:P(A;;GA;;;SY)(A;;GA;;;BA)", 1)
            encoded = ctypes.create_string_buffer(bytes(descriptor))
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), ctypes.cast(encoded, ctypes.c_void_p), False)
            desktop = user.CreateDesktopW("ClipBridge-CI-" + uuid.uuid4().hex, None, None, 0, 0x1FF, ctypes.byref(attributes))
            if not desktop or not user.SetThreadDesktop(desktop):
                raise ctypes.WinError(ctypes.get_last_error())
            def procedure(hwnd, message, wparam, lparam):
                if message == win32con.WM_KEYDOWN and wparam == ord("A"):
                    self.key.set()
                return win32gui.DefWindowProc(hwnd, message, wparam, lparam)
            klass = win32gui.WNDCLASS()
            klass.lpfnWndProc = procedure
            klass.hInstance = win32api.GetModuleHandle(None)
            klass.lpszClassName = "ClipBridgePrivateInputProbe" + uuid.uuid4().hex
            atom = win32gui.RegisterClass(klass)
            window = win32gui.CreateWindow(atom, "ClipBridge CI input target", win32con.WS_OVERLAPPEDWINDOW,
                0, 0, 640, 480, 0, 0, klass.hInstance, None)
            if not user.SwitchDesktop(desktop):
                raise ctypes.WinError(ctypes.get_last_error())
            win32gui.ShowWindow(window, win32con.SW_SHOW)
            win32gui.SetForegroundWindow(window)
            win32gui.SetFocus(window)
            self.ready.set()
            while not self.done.wait(.01):
                win32gui.PumpWaitingMessages()
                self.cursor = win32gui.GetCursorPos()
        except Exception as error:
            self.error = repr(error)
            self.ready.set()
        finally:
            if previous:
                user.SwitchDesktop(previous)
            if window:
                win32gui.DestroyWindow(window)
            if previous:
                user.SetThreadDesktop(previous)
            if desktop:
                user.CloseDesktop(desktop)
            if previous:
                user.CloseDesktop(previous)


def verify(peer):
    # The service deliberately targets only the active console. A desktop in a
    # different session cannot establish an equivalent secure-input test.
    session = ctypes.c_uint32()
    if not ctypes.WinDLL("kernel32", use_last_error=True).ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise ctypes.WinError(ctypes.get_last_error())
    if session.value != win32ts.WTSGetActiveConsoleSessionId():
        raise RuntimeError("CI test process is not in the active console session")
    probe = Probe()
    probe.thread.start()
    try:
        assert probe.ready.wait(8), "Private input desktop was not ready"
        assert probe.error is None, probe.error
        time.sleep(.8)  # The native engine checks the input desktop every 200ms.
        peer.send(b"CINN" + struct.pack("!HHIH", 180, 140, 1, 0))
        peer.send(b"DMMV" + struct.pack("!HH", 180, 140))
        peer.send(b"DMDN\x01")
        peer.send(b"DMUP\x01")
        peer.send(b"DKDN" + struct.pack("!HHH", ord("a"), 0, 30))
        peer.send(b"DKUP" + struct.pack("!HHH", ord("a"), 0, 30))
        assert probe.key.wait(6), "Native SYSTEM input did not reach the private desktop window"
        assert probe.cursor and abs(probe.cursor[0] - 180) <= 2 and abs(probe.cursor[1] - 140) <= 2, probe.cursor
        print("Native mutual-TLS mouse/key input on SYSTEM/Admin-only Windows desktop: PASS", flush=True)
    finally:
        peer.send(b"COUT")
        probe.done.set()
        probe.thread.join(timeout=8)
        assert not probe.thread.is_alive(), "Private input desktop was not restored"
