"""Native IPC framing and ACL hardening without launching any input engine."""
import os
import sys
import threading
import time
import uuid
import pytest

if sys.platform != "win32":
    pytest.skip("Windows core IPC", allow_module_level=True)

import win32con
import win32file
import win32pipe
import win32security
from clipbridge import windows_core_control as core


def test_own_pid_core_handshake_status_stop_and_restricted_acl(monkeypatch):
    address = r"\\.\pipe\ClipBridgeNativeTest-" + uuid.uuid4().hex
    monkeypatch.setattr(core, "ADDRESS", address)
    pipe = win32pipe.CreateNamedPipe(address, win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT, 1, 4096, 4096, 0, None)
    stopped, errors = threading.Event(), []
    def server():
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            assert win32file.ReadFile(pipe, 4096)[1] == b"hello=ClipBridge\n"
            win32file.WriteFile(pipe, b"versionMismatch=1.27.0+abc\n")
            assert win32file.ReadFile(pipe, 4096)[1] == b"hello=1.27.0+abc\n"
            win32file.WriteFile(pipe, b"connectionState=Connected\n")
            assert win32file.ReadFile(pipe, 4096)[1] == b"stop\n"
            stopped.set()
        except Exception as error:
            errors.append(error)
        finally:
            pipe.Close()
    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    control = core.CoreControl(os.getpid())
    try:
        end = time.monotonic() + 3
        while time.monotonic() < end and not control.connected:
            control.poll()
            time.sleep(.01)
        assert control.connected, errors
        descriptor = win32security.GetSecurityInfo(control.handle, win32security.SE_FILE_OBJECT,
                                                   win32security.DACL_SECURITY_INFORMATION)
        acl = descriptor.GetSecurityDescriptorDacl()
        allowed = {win32security.ConvertSidToStringSid(acl.GetAce(i)[2]) for i in range(acl.GetAceCount())
                   if acl.GetAce(i)[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE}
        assert allowed == {"S-1-5-18", "S-1-5-32-544"}
        control.stop()
        assert stopped.wait(3), errors
    finally:
        control.close()
        thread.join(timeout=3)
    assert not errors
