"""Linux settings encryption with an owner-only local wrapping key."""
import base64
import os
from pathlib import Path
import secrets
import stat

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def key_path():
    from .config import app_directory
    import sys
    if "--smoke-test" in sys.argv and os.environ.get("CLIPBRIDGE_TEST_DATA"):
        return Path(os.environ["CLIPBRIDGE_TEST_DATA"]) / "local.key"
    return app_directory() / "local.key"


def local_key():
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Linux 암호화 키의 소유자와 권한(600)을 확인하세요.")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        key = stream.read(33)
    if len(key) != 32:
        raise ValueError("Linux local key is invalid")
    return key


def protect(data):
    nonce = secrets.token_bytes(12)
    return "LIN1-" + base64.b64encode(nonce + AESGCM(local_key()).encrypt(nonce, data, b"ClipBridge-linux-v1")).decode("ascii")


def unprotect(value):
    if not value.startswith("LIN1-"):
        raise ValueError("다른 운영체제의 설정 파일은 사용할 수 없습니다.")
    raw = base64.b64decode(value[5:], validate=True)
    return AESGCM(local_key()).decrypt(raw[:12], raw[12:], b"ClipBridge-linux-v1")
