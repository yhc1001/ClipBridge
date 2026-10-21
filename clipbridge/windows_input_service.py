"""SYSTEM broker for one pinned input core; no remote/local command execution API."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pywintypes
import win32api
import win32con
import win32event
import win32file
import win32job
import win32pipe
import win32process
import win32security
import win32service
import win32serviceutil
import win32ts
from multiprocessing.connection import PipeConnection

from .input_engine import defaults, native_library_path, prepare_profile
from .security import protect
from .service_policy import MAX_REQUEST, canonical_identity, validate_request, validate_settings
from .windows_service_client import PIPE, REGISTRY_KEY, SERVICE_NAME, process_identity


def owner_sid():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        value = winreg.QueryValueEx(key, "OwnerSid")[0]
    win32security.ConvertStringSidToSid(value)
    if value in ("S-1-1-0", "S-1-5-18", "S-1-5-32-544"):
        raise ValueError("Installer must enroll an individual user")
    return value


def security_attributes(owner=None):
    # Do not grant FILE_CREATE_PIPE_INSTANCE to the user. GENERIC_WRITE would
    # include that right and permit an extra server instance under our name.
    descriptor = "D:P(A;;GA;;;SY)(A;;GA;;;BA)" + (f"(A;;0x12018b;;;{owner})" if owner else "")
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(descriptor, 1)
    return attributes


def secure_directory(path):
    from .files import assert_local_regular
    if not path.exists():
        win32file.CreateDirectory(str(path), security_attributes())
    assert_local_regular(path)
    descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT, win32security.OWNER_SECURITY_INFORMATION)
    if win32security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) not in ("S-1-5-18", "S-1-5-32-544"):
        raise PermissionError("Untrusted pre-existing service directory")
    protected = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor("D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", 1)
    win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, protected.GetSecurityDescriptorDacl(), None)


def create_input_process(program, arguments, environment, session):
    """Use our own SYSTEM token, never borrow a user's/winlogon's credentials."""
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
    primary = process = thread = job = None
    try:
        privileges = [win32security.SE_TCB_NAME, win32security.SE_ASSIGNPRIMARYTOKEN_NAME, win32security.SE_INCREASE_QUOTA_NAME]
        win32security.AdjustTokenPrivileges(token, False, [(win32security.LookupPrivilegeValue(None, name), win32con.SE_PRIVILEGE_ENABLED) for name in privileges])
        primary = win32security.DuplicateTokenEx(token, win32security.SecurityImpersonation, win32con.TOKEN_ALL_ACCESS, win32security.TokenPrimary)
        win32security.SetTokenInformation(primary, win32security.TokenSessionId, session)
        set_information = ctypes.WinDLL("advapi32", use_last_error=True).SetTokenInformation
        set_information.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        access = ctypes.c_uint32(1)
        if not set_information(int(primary), 26, ctypes.byref(access), ctypes.sizeof(access)):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = win32process.STARTUPINFO()
        startup.lpDesktop = r"winsta0\default"
        flags = win32con.CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW
        with native_library_path():
            process, thread, pid, _ = win32process.CreateProcessAsUser(primary, program,
                subprocess.list2cmdline([program, *arguments]), None, None, False, flags, environment, str(Path(program).parent), startup)
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        win32job.AssignProcessToJobObject(job, process)
        child_token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
        try:
            info = {"sid": win32security.ConvertSidToStringSid(win32security.GetTokenInformation(child_token, win32security.TokenUser)[0]),
                    "session": win32security.GetTokenInformation(child_token, win32security.TokenSessionId)}
            get_information = ctypes.WinDLL("advapi32", use_last_error=True).GetTokenInformation
            get_information.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
            actual_access, required = ctypes.c_uint32(), ctypes.c_uint32()
            if not get_information(int(child_token), 26, ctypes.byref(actual_access), 4, ctypes.byref(required)):
                raise ctypes.WinError(ctypes.get_last_error())
            info["ui_access"] = bool(actual_access.value)
        finally:
            child_token.Close()
        win32process.ResumeThread(thread)
        return process, job, pid, info
    except Exception:
        if process:
            win32api.TerminateProcess(process, 1)
            process.Close()
        if job:
            job.Close()
        raise
    finally:
        if thread:
            thread.Close()
        if primary:
            primary.Close()
        token.Close()


class InputController:
    def __init__(self, directory, owner):
        self.directory = directory
        secure_directory(directory)
        self.path = directory / "input-settings.json"
        self.lock = threading.RLock()
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.owner = owner
        if self.state and self.state.get("owner") != owner:
            self.state = {}
            self.path.unlink()
        if self.state:
            self.state["settings"] = validate_settings(self.state["settings"])
        self.armed = bool(self.state.get("settings", {}).get("enabled"))
        self.generation = 0
        self.child = self.job = None
        self.pid, self.session, self.applied = 0, None, -1
        self.profile = directory / "runtime"
        self.last_error = ""
        self.identity = {}
        self.next_start = 0
        self.core_control = None
        self.core_started = 0

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state), encoding="utf-8")
        temporary.replace(self.path)

    def stop_child(self):
        if self.child and self.core_control:
            try:
                self.core_control.stop()
                win32event.WaitForSingleObject(self.child, 2000)
            except Exception:
                pass
        if self.core_control:
            self.core_control.close()
            self.core_control = None
        if self.job:
            self.job.Close()
            self.job = None
        if self.child:
            win32event.WaitForSingleObject(self.child, 3000)
            self.child.Close()
            self.child = None
        self.pid = 0
        self.identity = {}
        try:
            from .windows_input_firewall import update
            update()
        except Exception:
            pass
        if self.profile.exists():
            from .files import assert_local_regular
            assert_local_regular(self.profile)
            shutil.rmtree(self.profile)

    def dispatch(self, request):
        operation = validate_request(request)
        with self.lock:
            if operation == "configure":
                settings = validate_settings(request["settings"])
                raw = canonical_identity(base64.b64decode(request["identity"], validate=True))
                digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode() + raw).hexdigest()
                if self.state.get("digest") != digest:
                    self.state = {"settings": settings, "protected_identity": protect(raw), "digest": digest, "owner": self.owner}
                    self.save()
                    self.generation += 1
                self.armed = settings["enabled"]
                self.next_start = 0
            elif operation in ("stop", "suspend"):
                self.armed = False
                if operation == "stop" and self.state:
                    self.state["settings"]["enabled"] = False
                    self.state["digest"] = ""
                    self.save()
                self.stop_child()
            return {"ok": True, "enabled": self.armed, "pid": self.pid, "session": self.session,
                    "service": SERVICE_NAME, "error": self.last_error, "identity": self.identity,
                    "native_ipc_secured": self.core_control is not None,
                    "connected": bool(self.core_control and self.core_control.connected)}

    def tick(self):
        with self.lock:
            session = win32ts.WTSGetActiveConsoleSessionId()
            alive = self.child and win32process.GetExitCodeProcess(self.child) == win32con.STILL_ACTIVE
            if self.child and not alive:
                self.last_error = "InputCoreExited:" + str(win32process.GetExitCodeProcess(self.child))
            if alive:
                try:
                    if self.core_control is None:
                        from .windows_core_control import CoreControl
                        self.core_control = CoreControl(self.pid)
                    self.core_control.poll()
                except Exception as error:
                    if time.monotonic() - self.core_started >= 3:
                        self.last_error = "InputCoreIpc:" + type(error).__name__
                        self.stop_child()
                        self.next_start = time.monotonic() + 5
                    return
            restart = session != self.session or self.applied != self.generation or not alive
            if not self.armed or session == 0xFFFFFFFF:
                if self.child:
                    self.stop_child()
                return
            if not restart or time.monotonic() < self.next_start:
                if alive:
                    self.last_error = ""
                return
            self.stop_child()
            self.next_start = time.monotonic() + 5
            try:
                settings = {**defaults(), **self.state["settings"], "protected_identity": self.state["protected_identity"]}
                program, arguments, environment = prepare_profile(SimpleNamespace(), settings, self.profile, copy_windows_runtime=False)
                if settings["mode"] == "server":
                    from .windows_input_firewall import update
                    update(program, settings["port"])
                env = {key: environment.value(key) for key in environment.keys()}
                self.child, self.job, self.pid, self.identity = create_input_process(program, arguments, env, session)
                self.core_started = time.monotonic()
                self.session, self.applied = session, self.generation
            except Exception as error:
                # Report only a source location, never settings, certificates or
                # private values from a traceback/local variables.
                import traceback
                site = traceback.extract_tb(error.__traceback__)[-1]
                self.last_error = (type(error).__name__ + ":" + str(getattr(error, "winerror", ""))
                                   + ":" + Path(site.filename).name + ":" + str(site.lineno))
                self.stop_child()


class ClipBridgeInputService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = "ClipBridge Input (UAC)"
    _svc_description_ = "ClipBridge authenticated mouse and keyboard on Windows secure desktops."

    def __init__(self, arguments):
        super().__init__(arguments)
        self.stop_event = win32event.CreateEvent(None, True, False, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcShutdown(self):
        self.SvcStop()

    def pipe_loop(self, controller, owner):
        while win32event.WaitForSingleObject(self.stop_event, 0) != win32event.WAIT_OBJECT_0:
            handle = None
            try:
                handle = win32pipe.CreateNamedPipe(PIPE, win32pipe.PIPE_ACCESS_DUPLEX | win32con.FILE_FLAG_OVERLAPPED | 0x80000,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT | 0x8,
                    1, MAX_REQUEST + 16, MAX_REQUEST + 16, 2000, security_attributes(owner))
                overlap = pywintypes.OVERLAPPED()
                overlap.hEvent = win32event.CreateEvent(None, True, False, None)
                try:
                    try:
                        win32pipe.ConnectNamedPipe(handle, overlap)
                    except pywintypes.error as error:
                        if error.winerror == 535:
                            win32event.SetEvent(overlap.hEvent)
                        elif error.winerror != 997:
                            raise
                    result = win32event.WaitForMultipleObjects([self.stop_event, overlap.hEvent], False, win32event.INFINITE)
                    if result == win32event.WAIT_OBJECT_0:
                        win32file.CancelIo(handle)
                        try:
                            win32file.GetOverlappedResult(handle, overlap, True)
                        except pywintypes.error:
                            pass
                        break
                finally:
                    overlap.hEvent.Close()
                sid, _ = process_identity(win32pipe.GetNamedPipeClientProcessId(handle))
                if sid != owner:
                    raise PermissionError("Unexpected local client SID")
                with PipeConnection(handle.Detach()) as connection:
                    if not connection.poll(3):
                        continue
                    try:
                        payload = json.loads(connection.recv_bytes(MAX_REQUEST))
                        response = controller.dispatch(payload)
                    except Exception as error:
                        response = {"ok": False, "error": "Input service request rejected: " + type(error).__name__}
                    connection.send_bytes(json.dumps(response).encode())
            except (OSError, pywintypes.error, EOFError, ValueError):
                win32event.WaitForSingleObject(self.stop_event, 100)
            finally:
                if handle:
                    handle.Close()

    def SvcDoRun(self):
        try:
            self.run_service()
        except Exception:
            import servicemanager, traceback
            servicemanager.LogErrorMsg("ClipBridgeInput startup failure:\n" + traceback.format_exc())
            raise

    def run_service(self):
        manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        service = win32service.OpenService(manager, SERVICE_NAME, win32service.SERVICE_CHANGE_CONFIG | win32service.SERVICE_START)
        try:
            win32service.ChangeServiceConfig2(service, win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
                {"ResetPeriod": 86400, "RebootMsg": None, "Command": None,
                 "Actions": [(win32service.SC_ACTION_RESTART, 5000)] * 3})
        finally:
            win32service.CloseServiceHandle(service)
            win32service.CloseServiceHandle(manager)
        owner = owner_sid()
        manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        access = win32con.READ_CONTROL | win32con.WRITE_DAC
        service = win32service.OpenService(manager, SERVICE_NAME, access)
        try:
            descriptor = win32service.QueryServiceObjectSecurity(service, win32security.DACL_SECURITY_INFORMATION)
            acl = descriptor.GetSecurityDescriptorDacl()
            present = any(acl.GetAce(index)[0][0] == 0 and acl.GetAce(index)[1] & 0x20035 == 0x20035
                          and win32security.ConvertSidToStringSid(acl.GetAce(index)[2]) == owner for index in range(acl.GetAceCount()))
            if not present:
                acl.AddAccessAllowedAce(win32security.ACL_REVISION, 0x20035, win32security.ConvertStringSidToSid(owner))
            descriptor.SetSecurityDescriptorDacl(True, acl, False)
            win32service.SetServiceObjectSecurity(service, win32security.DACL_SECURITY_INFORMATION, descriptor)
        finally:
            win32service.CloseServiceHandle(service)
            win32service.CloseServiceHandle(manager)
        controller = InputController(Path(os.environ["ProgramData"]) / "ClipBridgeInputService", owner)
        listener = threading.Thread(target=self.pipe_loop, args=(controller, owner), daemon=True)
        listener.start()
        try:
            while win32event.WaitForSingleObject(self.stop_event, 500) != win32event.WAIT_OBJECT_0:
                controller.tick()
        finally:
            win32event.SetEvent(self.stop_event)
            listener.join(timeout=4)
            with controller.lock:
                controller.stop_child()
