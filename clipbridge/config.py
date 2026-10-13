from __future__ import annotations

import json
import os
import secrets
import sys
import uuid
import winreg
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .model import MAX_CLIP, MAX_TOTAL, private_address, valid_id
from .security import make_identity, protect, unprotect


def app_directory() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "ClipBridge"


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
    text: bool = True
    images: bool = True
    files: bool = True
    file_policy: str = "ask"
    direction: str = "both"
    paused: bool = False
    autostart: bool = False
    clip_limit_mb: int = 96
    file_limit_mb: int = 512

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
        if self.role not in ("main", "server") or self.direction not in ("both", "main_to_server") or self.file_policy not in ("ask", "allow", "block"):
            raise ValueError("설정 값이 올바르지 않습니다.")
        if not 1024 <= self.port <= 65535 or not 1 <= self.clip_limit_mb <= MAX_CLIP // 1024**2 or not 1 <= self.file_limit_mb <= 1024:
            raise ValueError("포트 또는 용량 범위를 확인하세요.")
        private_address(self.bind_ip, bind=True)
        if connection:
            private_address(self.peer_ip)
            if self.role == "server" and (not self.peer_pin or not self.peer_id):
                raise ValueError("newserver에서 Main의 연결 코드를 먼저 등록하세요.")

    def can_send(self):
        return not self.paused and (self.direction == "both" or self.role == "main")

    def can_receive(self):
        return not self.paused and (self.direction == "both" or self.role == "server")


class ConfigStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or app_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"

    def load(self) -> Config:
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            config = Config(**{k: v for k, v in value.items() if k in Config.__dataclass_fields__})
            config.validate(connection=False)
            if len(config.secret) != 32:
                raise ValueError("DPAPI secret error")
            return config
        config = Config()
        config.protected_secret = protect(secrets.token_bytes(32))
        config.cert_pem, config.protected_key = make_identity(config.device_id)
        self.save(config)
        return config

    def save(self, config):
        config.validate(connection=False)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)


def set_autostart(enabled: bool):
    command = f'"{sys.executable}" --background' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "main.py"}" --background'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "ClipBridge", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "ClipBridge")
            except FileNotFoundError:
                pass
