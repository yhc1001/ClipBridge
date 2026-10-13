"""One instance per user; OS handles are released on exit/crash."""
import sys


class InstanceLock:
    def __init__(self, test_scope=None):
        self.handle = None
        self.acquired = False
        suffix = ""
        if test_scope:
            import uuid
            suffix = "-test-" + str(uuid.UUID(test_scope))
        if sys.platform == "win32":
            import win32api, win32event, win32security, win32con
            token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
            try:
                sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
            finally:
                token.Close()
            self.handle = win32event.CreateMutex(None, False, "Global\\ClipBridge-v1-" + sid + suffix)
            self.acquired = win32api.GetLastError() != 183
        else:
            import fcntl
            from .config import app_directory
            directory = app_directory()
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.handle = (directory / ("instance" + suffix + ".lock")).open("a")
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
            except BlockingIOError:
                pass

    def close(self):
        if self.handle is None:
            return
        if sys.platform == "win32":
            self.handle.Close()
        else:
            self.handle.close()
        self.handle = None
