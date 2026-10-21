from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .model import MAX_CLIP, MAX_TOTAL, private_address, valid_id
from .security import make_identity, protect, unprotect

CONFIG_LOCK = threading.RLock()


def app_directory() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "ClipBridge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ClipBridge"
    if sys.platform.startswith("linux"):
        return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "ClipBridge"
    raise RuntimeError("Unsupported operating system")


@dataclass
class Config:
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: str = "main"
    peer_ip: str = ""
    bind_ip: str = "0.0.0.0"
    port: int = 45832
    peer_id: str = ""
    peer_pin: str = ""
    protected_secret: str = ""
    cert_pem: str = ""
    protected_key: str = ""
    trusted_peers: dict = field(default_factory=dict)
    text: bool = True
    images: bool = True
    files: bool = True
    file_policy: str = "allow"
    file_policy_version: int = 1
    file_allow_ids: list = field(default_factory=list)
    direction: str = "both"
    paused: bool = False
    autostart: bool = True
    clip_limit_mb: int = 256
    file_limit_mb: int = 16384
    limits_version: int = 1
    input_settings: dict = field(default_factory=dict)
    mouse_enabled: bool = True
    input_defaults_version: int = 1

    @property
    def secret(self):
        return unprotect(self.protected_secret)

    @property
    def clip_limit(self):
        return min(MAX_CLIP, self.clip_limit_mb * 1024 * 1024)

    @property
    def file_limit(self):
        return min(MAX_TOTAL, self.file_limit_mb * 1024 * 1024)

    def validate(self, connection=True):
        valid_id(self.device_id)
        if self.peer_id:
            valid_id(self.peer_id)
        if not isinstance(self.trusted_peers, dict) or len(self.trusted_peers) > 16:
            raise ValueError("허브에는 최대 16대를 등록할 수 있습니다.")
        for device, record in self.trusted_peers.items():
            valid_id(device)
            if device == self.device_id or not isinstance(record, dict) or not isinstance(record.get("secret"), str) or not isinstance(record.get("name", ""), str):
                raise ValueError("등록된 장치 정보를 확인하세요.")
        if not isinstance(self.file_allow_ids, list) or len(self.file_allow_ids) > 32:
            raise ValueError("파일 승인 설정을 확인하세요.")
        for device in self.file_allow_ids:
            valid_id(device)
        if self.role not in ("main", "server") or self.direction not in ("both", "main_to_server") or self.file_policy not in ("ask", "allow", "block"):
            raise ValueError("설정 값이 올바르지 않습니다.")
        if not 1024 <= self.port <= 65535 or not 1 <= self.clip_limit_mb <= MAX_CLIP // 1024**2 or not 1 <= self.file_limit_mb <= MAX_TOTAL // 1024**2:
            raise ValueError("포트 또는 용량 범위를 확인하세요.")
        private_address(self.bind_ip, bind=True)
        if connection:
            if self.role == "server":
                private_address(self.peer_ip)
                if not self.peer_pin or not self.peer_id:
                    raise ValueError("상대 PC의 IP로 연결을 요청하고 승인받으세요.")

    def migrate_trust(self):
        """Keep the old 1:1 peer's key; issue a separate invitation for new devices."""
        if self.role == "main" and self.peer_id:
            self.trusted_peers.setdefault(self.peer_id, {"secret": self.protected_secret, "name": "기존 컴퓨터"})
            self.peer_id = self.peer_pin = ""
            self.protected_secret = protect(secrets.token_bytes(32))
            return True
        return False

    def can_send(self):
        return not self.paused and (self.direction == "both" or self.role == "main")

    def can_receive(self):
        return not self.paused and (self.direction == "both" or self.role == "server")


class ConfigStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or app_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            self.directory.chmod(0o700)
        self.path = self.directory / "settings.json"
        self.lock = threading.RLock()

    def load(self) -> Config:
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            config = Config(**{k: v for k, v in value.items() if k in Config.__dataclass_fields__})
            config.validate(connection=False)
            if len(config.secret) != 32:
                raise ValueError("DPAPI secret error")
            changed = config.migrate_trust()
            if "input_defaults_version" not in value:
                # Remove the old implicit quarter-second barrier in unified
                # groups once. Preserve explicit/manual and later choices.
                native = config.input_settings
                if (native.get("easy_controller") or native.get("easy_peers")) and native.get("switch_delay") == 250:
                    native["switch_delay"] = 0
                changed = True
            # Unified IP/approval groups always share in both directions. The
            # legacy one-way selector is no longer exposed in that workflow.
            if (config.input_settings.get("easy_controller") or config.input_settings.get("easy_peers")) and config.direction != "both":
                config.direction = "both"
                changed = True
            if "mouse_enabled" not in value and config.input_settings:
                config.mouse_enabled = bool(config.input_settings.get("enabled", False))
                changed = True
            if config.input_settings.get("certificate"):
                from .input_engine import migrate_identity
                try:
                    changed = migrate_identity(config.input_settings) or changed
                except (OSError, ValueError):
                    # Missing/invalid legacy identity must not break clipboard
                    # startup. Stop input until the user registers the new pin.
                    config.input_settings.update(certificate="", enabled=False, identity_missing=True)
                    changed = True
            if "file_policy_version" not in value:
                # Upgrade the old confirmation default once. Later explicit
                # manual approval/block choices remain unchanged on restart.
                if config.file_policy == "ask":
                    config.file_policy = "allow"
                changed = True
            if "limits_version" not in value:
                if config.clip_limit_mb == 96:
                    config.clip_limit_mb = 256
                if config.file_limit_mb == 512:
                    config.file_limit_mb = 16384
                changed = True
            if changed:
                self.save(config)
            return config
        config = Config()
        config.protected_secret = protect(secrets.token_bytes(32))
        config.cert_pem, config.protected_key = make_identity(config.device_id)
        self.save(config)
        return config

    def save(self, config):
        with CONFIG_LOCK, self.lock:
            config.validate(connection=False)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
            if sys.platform != "win32":
                self.path.chmod(0o600)


def set_autostart(enabled: bool):
    if sys.platform.startswith("linux"):
        from .linux_startup import set_autostart as linux_autostart
        return linux_autostart(enabled)
    if sys.platform == "darwin":
        from .macos_startup import set_autostart as mac_autostart
        return mac_autostart(enabled)
    import winreg
    command = f'"{sys.executable}" --background' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "main.py"}" --background'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "ClipBridge", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "ClipBridge")
            except FileNotFoundError:
                pass
