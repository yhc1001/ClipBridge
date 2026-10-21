"""Manage an installed Deskflow core through its public settings interface.

No Deskflow source/binary is distributed with ClipBridge. Existing profiles are
read-only; generated portable profiles cannot execute enter/exit commands.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, QTimer

from .model import canonical, private_address
from .security import fingerprint, unprotect

SCREEN_BOOLEANS = {"halfDuplexCapsLock", "halfDuplexNumLock", "halfDuplexScrollLock", "switchCornerTopLeft", "switchCornerTopRight",
    "switchCornerBottomLeft", "switchCornerBottomRight", "weakX11Focus", "xtestIsXineramaUnaware"}
SCREEN_MODIFIERS = {"modifierAlt", "modifierAltGr", "modifierCtrl", "modifierMeta", "modifierShift", "modifierSuper"}


def screen_options(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid screen options")
    result = {}
    for key, item in value.items():
        if key in SCREEN_BOOLEANS and type(item) is bool:
            result[key] = item
        elif key in SCREEN_MODIFIERS and item in ("alt", "altgr", "ctrl", "meta", "shift", "super", "none"):
            result[key] = item
        elif key == "switchCornerSize" and type(item) is int and 0 <= item <= 1000:
            result[key] = item
        else:
            raise ValueError("Invalid screen option")
    return result


def computer_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", value):
        raise ValueError("컴퓨터 이름은 영문·숫자·점·밑줄·하이픈으로 입력하세요.")
    return value


def find_engine():
    candidates = [shutil.which("deskflow-core")]
    if sys.platform == "win32":
        candidates += [str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Deskflow" / "deskflow-core.exe")]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Deskflow.app/Contents/MacOS/deskflow-core", "/opt/homebrew/bin/deskflow-core", "/usr/local/bin/deskflow-core"]
    return next((str(Path(value).absolute()) for value in candidates if value and Path(value).is_file()), "")


def defaults():
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname())[:63].strip(".-") or "Computer"
    return {"enabled": False, "engine": find_engine(), "mode": "server", "name": name, "server_ip": "", "port": 24801,
            "screens": [{"name": name, "x": 1, "y": 1}], "trusted_servers": [], "trusted_clients": [],
            "certificate": "", "switch_delay": 250, "scroll_scale": 1.0, "invert_scroll": False, "relative_mouse": False}


def validate(settings):
    computer_name(settings["name"])
    if settings["mode"] not in ("server", "client") or not 1024 <= settings["port"] <= 65535:
        raise ValueError("마우스 역할과 포트를 확인하세요.")
    if settings["mode"] == "client":
        private_address(settings["server_ip"])
    if not isinstance(settings["screens"], list) or not 1 <= len(settings["screens"]) <= 17:
        raise ValueError("화면 배치는 1~17대까지 가능합니다.")
    names, positions = set(), set()
    for screen in settings["screens"]:
        name = computer_name(screen["name"])
        screen_options(screen.get("options", {}))
        x, y = screen["x"], screen["y"]
        if name.casefold() in names or type(x) is not int or type(y) is not int or not 0 <= x <= 8 or not 0 <= y <= 8 or (x, y) in positions:
            raise ValueError("화면 이름과 위치가 겹치지 않게 배치하세요 (0~8).")
        names.add(name.casefold())
        positions.add((x, y))
    if settings["mode"] == "server" and settings["name"].casefold() not in names:
        raise ValueError("화면 배치에 이 컴퓨터 이름을 포함하세요.")
    if settings["mode"] == "server":
        reached = {next((screen["x"], screen["y"]) for screen in settings["screens"] if screen["name"].casefold() == settings["name"].casefold())}
        while True:
            connected = reached | {position for position in positions if any(abs(position[0] - x) + abs(position[1] - y) == 1 for x, y in reached)}
            if connected == reached:
                break
            reached = connected
        if reached != positions:
            raise ValueError("모든 화면이 가로나 세로로 맞닿도록 배치하세요.")
    for key in ("trusted_servers", "trusted_clients"):
        if not isinstance(settings[key], list) or len(settings[key]) > 32 or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in settings[key]):
            raise ValueError("상대 컴퓨터의 인증 코드를 확인하세요.")
    if not 0 <= settings["switch_delay"] <= 5000 or not .1 <= settings["scroll_scale"] <= 10:
        raise ValueError("전환 지연 또는 스크롤 배율 범위를 확인하세요.")


def server_configuration(settings):
    validate(settings)
    # Deskflow 1.27 reads computer names and global options from its INI;
    # the external config supplies links and optional input-filter rules.
    rows = ["section: links"]
    positions = {(item["x"], item["y"]): item["name"] for item in settings["screens"]}
    for screen in settings["screens"]:
        rows.append("    " + screen["name"] + ":")
        for direction, dx, dy in (("left", -1, 0), ("right", 1, 0), ("up", 0, -1), ("down", 0, 1)):
            adjacent = positions.get((screen["x"] + dx, screen["y"] + dy))
            if adjacent:
                rows.append(f"        {direction} = {adjacent}")
    rows += ["end", "section: options", "end", ""]
    return "\n".join(rows)


def default_profile():
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Deskflow" / "Deskflow.conf"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Deskflow" / "Deskflow.conf"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "Deskflow" / "Deskflow.conf"


def import_profile(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("Deskflow 설정 파일을 찾지 못했습니다.")
    source = QSettings(str(path), QSettings.Format.IniFormat)
    data = defaults()
    data["name"] = str(source.value("core/computerName", data["name"]))
    data["mode"] = "client" if int(source.value("core/coreMode", 2)) == 1 else "server"
    data["port"] = int(source.value("core/port", 24800))
    data["server_ip"] = str(source.value("client/remoteHost", "")).split(",")[0]
    data["scroll_scale"] = float(source.value("client/yScrollScale", 1.0))
    data["invert_scroll"] = source.value("client/invertYScroll", False, type=bool)
    data["relative_mouse"] = source.value("server/relativeMouseMoves", False, type=bool)
    data["switch_delay"] = int(source.value("server/switchDelay", 250)) if source.value("server/enableSwitchDelay", True, type=bool) else 0
    width = max(1, min(9, int(source.value("server/gridWidth", 5))))
    screens = []
    for index in range(1, min(81, int(source.value("internalConfig/screens/size", 0))) + 1):
        name = str(source.value(f"internalConfig/screens/{index}/name", ""))
        if name:
            screens.append({"name": name, "x": (index - 1) % width, "y": (index - 1) // width})
    data["screens"] = screens or [{"name": data["name"], "x": 1, "y": 1}]
    for screen in data["screens"]:
        options, prefix = {}, "computer_" + screen["name"] + "/"
        for key in SCREEN_BOOLEANS | SCREEN_MODIFIERS | {"switchCornerSize"}:
            if source.contains(prefix + key):
                kind = bool if key in SCREEN_BOOLEANS else int if key == "switchCornerSize" else str
                options[key] = source.value(prefix + key, type=kind)
        if options:
            screen["options"] = screen_options(options)
    roots = [path.parent]
    if sys.platform == "win32":
        roots.append(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Deskflow")
    certificate = str(source.value("security/certificate", ""))
    for root in roots:
        if not certificate and (root / "tls" / "deskflow.pem").is_file():
            certificate = str(root / "tls" / "deskflow.pem")
        for kind in ("servers", "clients"):
            database = root / "tls" / ("trusted-" + kind)
            if database.is_file():
                pins = re.findall(r"(?im)^v2:sha256:([0-9a-f]{64})\s*$", database.read_text(encoding="utf-8"))
                data["trusted_" + kind] = list(dict.fromkeys(data["trusted_" + kind] + [pin.lower() for pin in pins]))
    data["certificate"] = certificate
    data["enabled"] = False
    validate(data)
    return data


def identity_pin(config, settings):
    if settings.get("certificate"):
        raw = Path(settings["certificate"]).read_bytes()
        match = re.search(br"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", raw, re.S)
        if not match:
            raise ValueError("Deskflow 인증서를 읽지 못했습니다.")
        cert = x509.load_pem_x509_certificate(match[0])
        return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return fingerprint(config.cert_pem)


def connection_code(config, settings):
    return "CBI1-" + base64.urlsafe_b64encode(canonical({"name": computer_name(settings["name"]), "pin": identity_pin(config, settings)})).decode("ascii")


def parse_code(value):
    if not value.startswith("CBI1-") or len(value) > 1024:
        raise ValueError("마우스 연결 코드를 확인하세요.")
    data = json.loads(base64.b64decode(value[5:], altchars=b"-_", validate=True))
    computer_name(data["name"])
    if not isinstance(data["pin"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["pin"]):
        raise ValueError("Invalid input certificate pin")
    return data


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    from .files import assert_local_regular
    assert_local_regular(path)
    if path.is_symlink():
        raise ValueError("Unsafe input directory")
    if sys.platform == "win32":
        import win32api, win32con, win32security
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        acl = win32security.ACL()
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, 3, win32con.GENERIC_ALL, sid)
        win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION, None, None, acl, None)
    else:
        path.chmod(0o700)


def prepare_profile(config, settings, directory):
    validate(settings)
    engine = Path(settings["engine"])
    if not engine.is_file() or engine.name.lower() not in ("deskflow-core", "deskflow-core.exe"):
        raise ValueError("Deskflow 1.27 이상을 설치하거나 deskflow-core 실행 파일을 선택하세요.")
    private_directory(directory)
    profile = directory / "settings"
    private_directory(profile)
    tls = profile / "tls"
    private_directory(tls)
    certificate = settings.get("certificate")
    if not certificate:
        certificate = str(tls / "identity.pem")
        Path(certificate).write_bytes(unprotect(config.protected_key) + config.cert_pem.encode("ascii"))
        Path(certificate).chmod(0o600)
    else:
        identity_pin(config, settings)
    for kind in ("servers", "clients"):
        (tls / ("trusted-" + kind)).write_text("".join("v2:sha256:" + pin + "\n" for pin in settings["trusted_" + kind]), encoding="ascii")
    server = profile / "server.conf"
    server.write_text(server_configuration(settings), encoding="utf-8")
    path = profile / "Deskflow.conf"
    target = QSettings(str(path), QSettings.Format.IniFormat)
    values = {"core/computerName": settings["name"], "core/port": settings["port"], "core/processMode": 0,
        "core/coreMode": 2 if settings["mode"] == "server" else 1, "core/enableEnterCommand": False, "core/enableExitCommand": False,
        "security/tlsEnabled": True, "security/checkPeerFingerprints": True, "security/certificate": certificate,
        "server/enableClipboard": False, "server/externalConfig": True, "server/externalConfigFile": str(server),
        "server/enableSwitchDelay": settings["switch_delay"] > 0, "server/switchDelay": settings["switch_delay"],
        "server/relativeMouseMoves": settings["relative_mouse"], "client/remoteHost": settings["server_ip"],
        "client/yScrollScale": settings["scroll_scale"], "client/invertYScroll": settings["invert_scroll"],
        "gui/enableUpdateCheck": False, "log/toFile": False, "log/level": "INFO"}
    for screen in settings["screens"]:
        values["computer_" + screen["name"] + "/name"] = screen["name"]
        for key, value in screen_options(screen.get("options", {})).items():
            values["computer_" + screen["name"] + "/" + key] = value
    for key, value in values.items():
        target.setValue(key, value)
    target.sync()
    program = str(engine)
    environment = QProcessEnvironment.systemEnvironment()
    if getattr(sys, "frozen", False):
        for variable in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            if environment.contains(variable + "_ORIG"):
                environment.insert(variable, environment.value(variable + "_ORIG"))
            else:
                environment.remove(variable)
        for variable in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            environment.remove(variable)
    private_directory(profile / "state")
    environment.insert("XDG_STATE_HOME", str(profile / "state"))
    environment.insert("XDG_CONFIG_HOME", str(profile))
    if sys.platform == "win32":
        # Deskflow's Windows core uses a global trust directory unless it is in
        # portable mode. A local executable copy isolates all profile/TLS writes.
        program = str(directory / "deskflow-core.exe")
        shutil.copyfile(engine, program)
        system = Path(os.environ["SystemRoot"])
        environment.insert("PATH", os.pathsep.join([str(engine.parent), str(system / "System32"), str(system)]))
        environment.insert("QT_PLUGIN_PATH", str(engine.parent / "plugins"))
    return program, [settings["mode"], "--settings", str(path), "--new-instance"], environment


@contextmanager
def native_library_path():
    """External Deskflow must load its own Qt, not the frozen application's Qt."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.restype = ctypes.c_int
    kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    buffer = ctypes.create_unicode_buffer(32768)
    kernel.GetDllDirectoryW(len(buffer), buffer)
    kernel.SetDllDirectoryW(None)
    try:
        yield
    finally:
        kernel.SetDllDirectoryW(buffer.value or None)


class InputManager(QObject):
    def __init__(self, config, directory, notify, parent=None):
        super().__init__(parent)
        self.config, self.directory, self.notify = config, directory, notify
        self.process, self.session = None, None
        self.retry = QTimer(self)
        self.retry.setInterval(5000)
        self.retry.timeout.connect(self.start)

    def start(self):
        settings = {**defaults(), **self.config.input_settings}
        if not settings["enabled"] or self.process is not None:
            return
        try:
            import psutil
            if any(process.info["name"] and process.info["name"].lower() in ("deskflow-core.exe", "deskflow-core", "deskflow-server.exe", "deskflow-client.exe") for process in psutil.process_iter(["name"])):
                raise ValueError("기존 Deskflow가 실행 중입니다. Deskflow에서 정지한 뒤 마우스 공유를 켜세요.")
            required = "trusted_servers" if settings["mode"] == "client" else "trusted_clients"
            if not settings[required]:
                raise ValueError("상대 마우스 연결 코드를 추가하거나 기존 Deskflow 설정을 가져오세요.")
            base = self.directory / "input-runtime"
            private_directory(base)
            # The application has a single-instance lock and no native core is
            # running. Remove private sessions left behind by an abnormal exit.
            for stale in base.glob("session-*"):
                from .files import assert_local_regular
                assert_local_regular(stale)
                if stale.is_dir() and not stale.is_symlink():
                    shutil.rmtree(stale)
            self.session = tempfile.TemporaryDirectory(prefix="session-", dir=base)
            program, args, environment = prepare_profile(self.config, settings, Path(self.session.name))
            self.process = QProcess(self)
            self.process.setProcessEnvironment(environment)
            self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.process.readyReadStandardOutput.connect(self.read_status)
            self.process.finished.connect(self.finished)
            self.process.errorOccurred.connect(lambda error: self.notify("input_status", "마우스 엔진 시작 실패 · Deskflow 설치 경로를 확인하세요"))
            self.process.errorOccurred.connect(self.process_error)
            with native_library_path():
                self.process.start(program, args)
            self.retry.stop()
            self.notify("input_status", "마우스·키보드 엔진 실행 중 · Scroll Lock으로 화면 이동 잠금")
        except Exception as error:
            if self.session:
                self.session.cleanup()
                self.session = None
            self.notify("input_status", str(error) if isinstance(error, ValueError) else "마우스 엔진을 시작하지 못했습니다 (" + type(error).__name__ + ")")

    def read_status(self):
        if not self.process:
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace").lower()
        if "connected" in text and "disconnected" not in text:
            self.notify("input_status", "마우스·키보드 연결됨")
        elif "fingerprint" in text and ("failed" in text or "not" in text or "untrusted" in text):
            self.notify("input_status", "마우스 인증 확인 필요 · 양쪽 연결 코드를 등록하세요")

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.finished()

    def finished(self, *args):
        if self.process:
            self.process.deleteLater()
        self.process = None
        if self.session:
            self.session.cleanup()
            self.session = None
        if self.config.input_settings.get("enabled"):
            self.notify("input_status", "마우스 연결 끊김 · 자동 재시도")
            self.retry.start()

    def stop(self):
        self.retry.stop()
        if self.process:
            process, self.process = self.process, None
            process.finished.disconnect(self.finished)
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
        if self.session:
            self.session.cleanup()
            self.session = None
