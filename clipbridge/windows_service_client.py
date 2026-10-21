"""Local-only, SID-checked input service transport; JSON bytes, never pickle."""
import base64
import ctypes
import json
import sys
import time
from pathlib import Path

PIPE = r"\\.\pipe\ClipBridgeInput-v1"
SERVICE_NAME = "ClipBridgeInput"
REGISTRY_KEY = r"SOFTWARE\ClipBridge\InputService"


def current_sid():
    import win32api, win32con, win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
    finally:
        token.Close()


def installation():
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            owner = winreg.QueryValueEx(key, "OwnerSid")[0]
            executable = winreg.QueryValueEx(key, "Executable")[0]
        if owner != current_sid() or not Path(executable).is_file():
            return None
        return {"owner": owner, "executable": str(Path(executable).resolve())}
    except OSError:
        return None


def process_identity(pid):
    import win32api, win32con, win32security
    process = win32api.OpenProcess(0x1000, False, pid)
    token = None
    try:
        path = process_path(process)
        token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
        sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
        return sid, path
    finally:
        if token:
            token.Close()
        process.Close()


def process_path(process):
    query = ctypes.WinDLL("kernel32", use_last_error=True).QueryFullProcessImageNameW
    query.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    buffer, length = ctypes.create_unicode_buffer(32768), ctypes.c_uint32(32768)
    if not query(int(process), 0, buffer, ctypes.byref(length)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def verify_server(pid, expected_path):
    import win32api, win32service
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    service = process = None
    try:
        service = win32service.OpenService(manager, SERVICE_NAME, win32service.SERVICE_QUERY_STATUS | win32service.SERVICE_QUERY_CONFIG)
        status = win32service.QueryServiceStatusEx(service)
        config = win32service.QueryServiceConfig(service)
        if status["ProcessId"] != pid or config[7].casefold() not in ("localsystem", "nt authority\\system"):
            raise PermissionError("Pipe server is not the installed SYSTEM service")
        process = win32api.OpenProcess(0x1000, False, pid)
        if Path(process_path(process)).resolve() != Path(expected_path):
            raise PermissionError("Pipe server image does not match installation")
    finally:
        if process:
            process.Close()
        if service:
            win32service.CloseServiceHandle(service)
        win32service.CloseServiceHandle(manager)


def request(message, timeout=2):
    import win32con, win32file, win32pipe
    from multiprocessing.connection import PipeConnection
    from .service_policy import MAX_REQUEST
    installed = installation()
    if not installed:
        raise RuntimeError("ClipBridge UAC 설치형이 등록되지 않았습니다.")
    payload = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode()
    if len(payload) > MAX_REQUEST:
        raise ValueError("Input service request too large")
    import pywintypes
    deadline = time.monotonic() + .8
    while True:
        try:
            win32pipe.WaitNamedPipe(PIPE, 100)
            handle = win32file.CreateFile(PIPE, win32con.GENERIC_READ | 0x2 | 0x100, 0, None,
                                        win32con.OPEN_EXISTING, win32con.FILE_FLAG_OVERLAPPED | 0x00110000, None)
            break
        except pywintypes.error as error:
            if error.winerror not in (2, 121, 231) or time.monotonic() >= deadline:
                raise
            time.sleep(.02)
    try:
        verify_server(win32pipe.GetNamedPipeServerProcessId(handle), installed["executable"])
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        connection = PipeConnection(handle.Detach())
    finally:
        handle.Close()
    with connection:
        connection.send_bytes(payload)
        if not connection.poll(timeout):
            raise TimeoutError("Input service did not respond")
        response = json.loads(connection.recv_bytes(16384))
    if not response.get("ok"):
        raise RuntimeError(response.get("error", "Input service rejected request"))
    return response


def control(start):
    import win32service
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    handle = None
    try:
        access = win32service.SERVICE_QUERY_STATUS | (win32service.SERVICE_START if start else win32service.SERVICE_STOP)
        handle = win32service.OpenService(manager, SERVICE_NAME, access)
        status = win32service.QueryServiceStatus(handle)[1]
        if start and status == win32service.SERVICE_STOPPED:
            win32service.StartService(handle, None)
        elif not start and status != win32service.SERVICE_STOPPED:
            win32service.ControlService(handle, win32service.SERVICE_CONTROL_STOP)
    finally:
        if handle:
            win32service.CloseServiceHandle(handle)
        win32service.CloseServiceHandle(manager)


def configure(config, settings):
    from .security import unprotect
    from .service_policy import public_settings
    control(True)
    identity = unprotect(settings["protected_identity"]) if settings.get("protected_identity") else unprotect(config.protected_key) + config.cert_pem.encode("ascii")
    return request({"operation": "configure", "settings": public_settings(settings), "identity": base64.b64encode(identity).decode("ascii")})
