"""Own-PID core IPC: tighten its legacy ACL and close it gracefully."""
import re
import win32con
import win32file
import win32pipe
import win32security

ADDRESS = r"\\.\pipe\deskflow-core"


class CoreControl:
    def __init__(self, pid):
        self.handle = win32file.CreateFile(ADDRESS, win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.WRITE_DAC,
            0, None, win32con.OPEN_EXISTING, 0x00110000, None)
        self.buffer = b""
        self.connected = False
        try:
            if win32pipe.GetNamedPipeServerProcessId(self.handle) != pid:
                raise PermissionError("Another input core owns the native IPC address")
            descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                "D:P(D;;GA;;;NU)(A;;GA;;;SY)(A;;GA;;;BA)", 1)
            win32security.SetSecurityInfo(self.handle, win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, descriptor.GetSecurityDescriptorDacl(), None)
            win32file.WriteFile(self.handle, b"hello=ClipBridge\n")
        except Exception:
            self.handle.Close()
            raise

    def poll(self):
        _, available, _ = win32pipe.PeekNamedPipe(self.handle, 0)
        if not available:
            return
        _, data = win32file.ReadFile(self.handle, min(available, 4096))
        self.buffer = (self.buffer + data)[-16384:]
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if line.startswith(b"versionMismatch="):
                version = line.split(b"=", 1)[1]
                if re.fullmatch(rb"[A-Za-z0-9.+_-]{1,128}", version):
                    win32file.WriteFile(self.handle, b"hello=" + version + b"\n")
            elif line.startswith(b"connectionState="):
                self.connected = line.split(b"=", 1)[1] == b"Connected"

    def stop(self):
        win32file.WriteFile(self.handle, b"stop\n")

    def close(self):
        self.handle.Close()
