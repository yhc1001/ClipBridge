"""Encrypt settings with an AES key held by the macOS login Keychain."""
import base64
import secrets
import threading
import os
import sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_key = None
_lock = threading.Lock()
_AAD = b"ClipBridge-settings-v1"


def keychain_key():
    global _key
    with _lock:
        if _key is not None:
            return _key
        import Security as S
        from Foundation import NSData
        service = "ClipBridge"
        if "--smoke-test" in sys.argv and os.environ.get("CLIPBRIDGE_SMOKE_INSTANCE"):
            import uuid
            service += ".test." + str(uuid.UUID(os.environ["CLIPBRIDGE_SMOKE_INSTANCE"]))
        query = {S.kSecClass: S.kSecClassGenericPassword, S.kSecAttrService: service, S.kSecAttrAccount: "local-settings-key-v1"}
        lookup = {**query, S.kSecReturnData: True, S.kSecMatchLimit: S.kSecMatchLimitOne}
        status, result = S.SecItemCopyMatching(lookup, None)
        if status == S.errSecItemNotFound:
            candidate = secrets.token_bytes(32)
            status, _ = S.SecItemAdd({**query, S.kSecValueData: NSData.dataWithBytes_length_(candidate, len(candidate))}, None)
            if status == S.errSecSuccess:
                _key = candidate
                return _key
            if status == S.errSecDuplicateItem:
                status, result = S.SecItemCopyMatching(lookup, None)
        if status != S.errSecSuccess or result is None or len(bytes(result)) != 32:
            raise RuntimeError("macOS 키체인 접근을 허용한 뒤 다시 실행하세요.")
        _key = bytes(result)
        return _key


def protect(data: bytes) -> str:
    nonce = secrets.token_bytes(12)
    return "MAC1-" + base64.b64encode(nonce + AESGCM(keychain_key()).encrypt(nonce, data, _AAD)).decode("ascii")


def unprotect(value: str) -> bytes:
    if not value.startswith("MAC1-"):
        raise ValueError("다른 운영체제의 설정 파일은 사용할 수 없습니다.")
    raw = base64.b64decode(value[5:], validate=True)
    if len(raw) < 28:
        raise ValueError("Invalid protected data")
    return AESGCM(keychain_key()).decrypt(raw[:12], raw[12:], _AAD)
