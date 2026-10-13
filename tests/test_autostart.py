import pytest
winreg = pytest.importorskip("winreg")
from clipbridge.config import set_autostart


def test_windows_login_registry_registration_and_removal():
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        try:
            original = winreg.QueryValueEx(key, "ClipBridge")
        except FileNotFoundError:
            original = None
    try:
        set_autostart(True)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, kind = winreg.QueryValueEx(key, "ClipBridge")
            assert kind == winreg.REG_SZ and value.startswith('"') and "--background" in value
        set_autostart(False)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            try:
                winreg.QueryValueEx(key, "ClipBridge")
                assert False, "registration must be removed"
            except FileNotFoundError:
                pass
    finally:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            if original:
                winreg.SetValueEx(key, "ClipBridge", 0, original[1], original[0])
            else:
                try:
                    winreg.DeleteValue(key, "ClipBridge")
                except FileNotFoundError:
                    pass
