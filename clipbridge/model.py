from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import threading
import uuid
from dataclasses import dataclass, field

MAX_CLIP = 512 * 1024 * 1024
MAX_FRAME = 180 * 1024 * 1024
MAX_FILES = 20000
MAX_TOTAL = 1024 * 1024 * 1024 * 1024
CHUNK = 256 * 1024
FORMATS = {"text", "PNG", "DIB", "DIBV5", "HTML Format", "Rich Text Format", "Rich Text Format Without Objects", "Sylk", "DIF"}
TEXT_FORMATS = {"text", "HTML Format", "Rich Text Format", "Rich Text Format Without Objects", "Sylk", "DIF"}
IMAGE_FORMATS = {"PNG", "DIB", "DIBV5"}


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def valid_id(value: str) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("invalid device/event ID")
    return value


def private_address(value: str, *, bind=False) -> str:
    try:
        address = ipaddress.ip_address(value.strip())
    except (ValueError, AttributeError):
        raise ValueError("상대 PC의 LAN 또는 Tailscale IP 주소를 입력하세요.") from None
    if bind and address.is_unspecified:
        return str(address)
    allowed = address.is_loopback or address.is_link_local
    if address.version == 4:
        allowed |= any(address in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"))
    else:
        allowed |= address in ipaddress.ip_network("fc00::/7")
    if not allowed or address.is_multicast or address.is_unspecified:
        raise ValueError("LAN/Tailscale IP 주소만 사용할 수 있습니다.")
    return str(address)


def safe_relative(value: str) -> str:
    if not isinstance(value, str) or len(value) > 220 or not value:
        raise ValueError("invalid path")
    parts = value.split("/")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((".", " ")) or
                any(ord(c) < 32 or c in '<>:"\\|?*' for c in part) or
                re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\..*)?", part)):
            raise ValueError("unsafe Windows path")
    return value


@dataclass(frozen=True, order=True)
class Stamp:
    counter: int
    device: str

    def wire(self):
        return [self.counter, self.device]

    @classmethod
    def parse(cls, value):
        if not isinstance(value, list) or len(value) != 2 or type(value[0]) is not int or not 0 < value[0] < 2**63:
            raise ValueError("invalid logical clock")
        return cls(value[0], valid_id(value[1]))


class Ledger:
    """Lamport clock + device UUID tie-break; no dependency on PC wall clocks."""
    def __init__(self, device: str):
        self.device = device
        self.clock = 0
        self.latest = Stamp(0, device)
        self.lock = threading.RLock()

    def local(self) -> Stamp:
        with self.lock:
            self.clock += 1
            self.latest = Stamp(self.clock, self.device)
            return self.latest

    def observe(self, counter):
        if type(counter) is not int or not 0 <= counter < 2**63:
            raise ValueError("invalid clock")
        with self.lock:
            self.clock = max(self.clock, counter)

    def claim(self, stamp: Stamp) -> bool:
        with self.lock:
            self.clock = max(self.clock, stamp.counter)
            if stamp <= self.latest:
                return False
            self.latest = stamp
            return True

    def current(self, stamp: Stamp) -> bool:
        with self.lock:
            return self.latest == stamp


@dataclass
class Snapshot:
    formats: dict[str, bytes] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    stamp: Stamp | None = None
    sequence: int = 0

    def digest(self) -> str:
        digest = hashlib.sha256()
        for name, data in sorted(self.formats.items()):
            tag = name.encode()
            digest.update(len(tag).to_bytes(4, "big") + tag + len(data).to_bytes(8, "big") + data)
        digest.update(canonical(self.paths))
        return digest.hexdigest()

    def wire(self):
        return {name: base64.b64encode(data).decode("ascii") for name, data in self.formats.items()}

    @classmethod
    def decode(cls, value: dict, limit=MAX_CLIP):
        if not isinstance(value, dict) or len(value) > len(FORMATS):
            raise ValueError("invalid formats")
        formats, total = {}, 0
        for name, encoded in value.items():
            if name not in FORMATS or not isinstance(encoded, str) or len(encoded) > limit * 4 // 3 + 4:
                raise ValueError("unsupported/oversized clipboard format")
            data = base64.b64decode(encoded, validate=True)
            total += len(data)
            if total > limit:
                raise ValueError("clipboard size limit")
            if name == "text":
                data.decode("utf-8", errors="strict")
                if b"\0" in data:
                    raise ValueError("embedded NUL")
            formats[name] = data
        if not formats:
            raise ValueError("empty clipboard")
        return cls(formats)

    def filtered(self, text=True, images=True):
        return Snapshot({k: v for k, v in self.formats.items() if (text and k in TEXT_FORMATS) or (images and k in IMAGE_FORMATS)}, [], self.stamp, self.sequence)
