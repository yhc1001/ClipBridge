from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import ssl
import tempfile
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .model import canonical, valid_id


def protect(data: bytes) -> str:
    if sys.platform == "win32":
        import win32crypt
        return base64.b64encode(win32crypt.CryptProtectData(data, "ClipBridge", None, None, None, 1)).decode("ascii")
    if sys.platform == "darwin":
        from .macos_security import protect as mac_protect
        return mac_protect(data)
    if sys.platform.startswith("linux"):
        from .linux_security import protect as linux_protect
        return linux_protect(data)
    raise RuntimeError("Unsupported operating system")


def unprotect(data: str) -> bytes:
    if sys.platform == "win32":
        import win32crypt
        return win32crypt.CryptUnprotectData(base64.b64decode(data, validate=True), None, None, None, 1)[1]
    if sys.platform == "darwin":
        from .macos_security import unprotect as mac_unprotect
        return mac_unprotect(data)
    if sys.platform.startswith("linux"):
        from .linux_security import unprotect as linux_unprotect
        return linux_unprotect(data)
    raise RuntimeError("Unsupported operating system")


def make_identity(device: str):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"ClipBridge {device}")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), protect(pem)


def fingerprint(cert_pem: str) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert_pem)).hexdigest()


def server_context(cert: str, protected_key: str) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # OpenSSL requires a key path. Delete it immediately after SSLContext loads it.
    with tempfile.TemporaryDirectory(prefix="ClipBridge-tls-") as directory:
        cert_path, key_path = Path(directory) / "cert.pem", Path(directory) / "key.pem"
        cert_path.write_text(cert, encoding="ascii")
        password = secrets.token_bytes(32)
        key = serialization.load_pem_private_key(unprotect(protected_key), password=None)
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password)))
        context.load_cert_chain(str(cert_path), str(key_path), password=password)
    return context


def client_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Explicit SHA-256 pin checked before application authentication.
    return context


def proof(secret: bytes, role: str, server_id: str, client_id: str, server_nonce: str, client_nonce: str) -> str:
    return hmac.new(secret, canonical(["ClipBridge-v1", role, server_id, client_id, server_nonce, client_nonce]), hashlib.sha256).hexdigest()


def pairing_token(config) -> str:
    return "CB1-" + base64.urlsafe_b64encode(canonical({"device": config.device_id, "pin": fingerprint(config.cert_pem), "secret": base64.b64encode(config.secret).decode("ascii")})).decode("ascii")


def parse_pairing(token: str):
    if not token.startswith("CB1-") or len(token) > 1024:
        raise ValueError("올바른 ClipBridge 연결 코드를 입력하세요.")
    value = json.loads(base64.b64decode(token[4:].strip(), altchars=b"-_", validate=True))
    valid_id(value["device"])
    pin = value["pin"]
    if not isinstance(pin, str) or len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin):
        raise ValueError("invalid certificate pin")
    secret = base64.b64decode(value["secret"], validate=True)
    if len(secret) != 32:
        raise ValueError("invalid secret")
    return value["device"], pin, secret


def nonce():
    return secrets.token_hex(32)


def valid_nonce(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid nonce")
    return value
