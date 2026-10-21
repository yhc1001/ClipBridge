"""Install and exercise the service ONLY on a disposable GitHub Windows runner."""
import os
import sys
if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("This installer/input test is restricted to disposable Windows CI runners")

import json
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import win32api
import win32con
import win32security
import win32service
import win32ts

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipbridge import __version__
from clipbridge.config import ConfigStore
from clipbridge.input_engine import defaults
from clipbridge.security import fingerprint, unprotect
from clipbridge import windows_service_client as service


def wait(predicate, seconds=30):
    end = time.monotonic() + seconds
    error = None
    while time.monotonic() < end:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exception:
            error = exception
        time.sleep(.15)
    raise RuntimeError("UAC service test timed out: " + repr(error))


def packet(connection, data):
    connection.sendall(struct.pack("!I", len(data)) + data)


def receive(connection):
    def exact(size):
        result = bytearray()
        while len(result) < size:
            value = connection.recv(size - len(result))
            if not value:
                raise EOFError()
            result.extend(value)
        return bytes(result)
    size = struct.unpack("!I", exact(4))[0]
    assert size <= 4 * 1024**2
    return exact(size)


class NativeTestPeer:
    def __init__(self, directory, server, client):
        cert, key = directory / "server.pem", directory / "server.key"
        cert.write_text(server.cert_pem)
        key.write_bytes(unprotect(server.protected_key))
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_cert_chain(cert, key)
        self.context.verify_mode = ssl.CERT_REQUIRED
        self.context.load_verify_locations(cadata=client.cert_pem)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.listener.settimeout(.5)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.count = 0
        self.connection = None
        self.error = None
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while not self.stop.is_set():
            connection = None
            try:
                raw, _ = self.listener.accept()
                raw.settimeout(3)
                connection = self.context.wrap_socket(raw, server_side=True)
                packet(connection, b"Barrier" + struct.pack("!HH", 1, 8))
                assert receive(connection).startswith(b"Barrier")
                packet(connection, b"QINF")
                while not receive(connection).startswith(b"DINF"):
                    pass
                packet(connection, b"CIAK")
                packet(connection, b"DSOP" + struct.pack("!I", 4) + b"CLPS" + struct.pack("!I", 0) + b"CLSZ" + struct.pack("!I", 0))
                self.connection = connection
                self.count += 1
                last = time.monotonic()
                connection.settimeout(.2)
                while not self.stop.is_set():
                    if time.monotonic() - last >= 1:
                        packet(connection, b"CALV")
                        last = time.monotonic()
                    try:
                        receive(connection)
                    except socket.timeout:
                        continue
            except socket.timeout:
                continue
            except (OSError, EOFError):
                pass
            except Exception as error:
                self.error = repr(error)
            finally:
                self.connection = None
                if connection:
                    connection.close()

    def close(self):
        self.stop.set()
        if self.connection:
            self.connection.close()
        self.listener.close()


def scm_status():
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    handle = win32service.OpenService(manager, service.SERVICE_NAME, win32service.SERVICE_QUERY_STATUS)
    try:
        return win32service.QueryServiceStatusEx(handle)
    finally:
        win32service.CloseServiceHandle(handle)
        win32service.CloseServiceHandle(manager)


def terminate(pid):
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY)
    try:
        win32security.AdjustTokenPrivileges(token, False, [(win32security.LookupPrivilegeValue(None, win32security.SE_DEBUG_NAME), win32con.SE_PRIVILEGE_ENABLED)])
    finally:
        token.Close()
    process = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
    try:
        win32api.TerminateProcess(process, 123)
    finally:
        process.Close()


def check():
    installer = ROOT / "dist" / ("v" + __version__) / "ClipBridge-UAC-setup-x64.msi"
    with tempfile.TemporaryDirectory(prefix="ClipBridge-service-CI-") as temporary:
        directory = Path(temporary)
        log = directory / "install.log"
        peer = None
        result = subprocess.run(["msiexec", "/i", str(installer), "/qn", "/norestart", "/l*v", str(log)], timeout=300)
        try:
            if result.returncode not in (0, 3010):
                print(log.read_text(encoding="utf-16", errors="replace")[-18000:])
                raise RuntimeError("MSI installation failed: " + str(result.returncode))
            wait(lambda: service.installation())
            wait(lambda: service.request({"operation": "status"}))
            print("MSI installation, enrolled owner, authenticated local SYSTEM service: PASS", flush=True)
            config = ConfigStore(directory / "client").load()
            server = ConfigStore(directory / "server").load()
            peer = NativeTestPeer(directory, server, config)
            settings = defaults()
            settings.update(enabled=True, mode="client", name="CIClient", server_ip="127.0.0.1", port=peer.port,
                trusted_servers=[fingerprint(server.cert_pem)], screens=[{"name": "CIClient", "x": 0, "y": 0}])
            service.configure(config, settings)
            wait(lambda: peer.count >= 1)
            status = service.request({"operation": "status"})
            assert status["pid"] and status["identity"]["sid"] == "S-1-5-18", status
            assert status["identity"]["ui_access"] and status["identity"]["session"] == win32ts.WTSGetActiveConsoleSessionId(), status
            print("Installed native core: mutual TLS, SYSTEM, active console session, UIAccess token: PASS", flush=True)
            try:
                service.request({"operation": "execute", "command": "not-allowed"})
                raise AssertionError("Service accepted arbitrary command")
            except RuntimeError:
                pass
            print("Service rejects arbitrary execution operation: PASS", flush=True)
            first = status["pid"]
            terminate(first)
            wait(lambda: peer.count >= 2)
            assert service.request({"operation": "status"})["pid"] != first
            print("Native input child crash automatic recovery: PASS", flush=True)
            daemon = scm_status()["ProcessId"]
            terminate(daemon)
            wait(lambda: peer.count >= 3, 45)
            assert scm_status()["ProcessId"] != daemon
            print("SCM service failure restart and persisted identity reconnect: PASS", flush=True)
            service.request({"operation": "stop"})
            assert service.request({"operation": "status"})["pid"] == 0
            print("Explicit stop closes input child: PASS", flush=True)
        finally:
            if peer:
                peer.close()
            removal = subprocess.run(["msiexec", "/x", str(installer), "/qn", "/norestart"], timeout=180)
            assert removal.returncode in (0, 1605, 3010), removal.returncode
            assert service.installation() is None
            print("MSI service and registration removal: PASS", flush=True)


if __name__ == "__main__":
    check()
