"""Closed input-service protocol: settings and an identity, never commands/paths."""
import copy
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from .input_engine import defaults, validate

MAX_REQUEST = 128 * 1024
SETTING_KEYS = {"enabled", "mode", "name", "server_ip", "port", "screens", "trusted_servers", "trusted_clients",
                "switch_delay", "scroll_scale", "invert_scroll", "relative_mouse"}


def public_settings(settings):
    return {key: copy.deepcopy(settings[key]) for key in SETTING_KEYS}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != SETTING_KEYS:
        raise ValueError("Unexpected input service settings")
    settings = {**defaults(), **copy.deepcopy(value)}
    for key in ("enabled", "invert_scroll", "relative_mouse"):
        if type(settings[key]) is not bool:
            raise ValueError("Invalid input flag")
    for screen in settings["screens"]:
        if not isinstance(screen, dict) or not {"name", "x", "y"} <= set(screen) or set(screen) - {"name", "x", "y", "options"}:
            raise ValueError("Invalid input screen")
    validate(settings)
    if settings["enabled"] and not settings["trusted_clients" if settings["mode"] == "server" else "trusted_servers"]:
        raise ValueError("Register an input peer first")
    return public_settings(settings)


def canonical_identity(raw):
    if not isinstance(raw, bytes) or not 200 <= len(raw) <= 16384:
        raise ValueError("Invalid input identity size")
    cert = x509.load_pem_x509_certificate(raw)
    key = serialization.load_pem_private_key(raw, password=None)
    if not (isinstance(key, ec.EllipticCurvePrivateKey) or isinstance(key, rsa.RSAPrivateKey) and 2048 <= key.key_size <= 4096):
        raise ValueError("Unsupported input identity key")
    encoding, form = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    if cert.public_key().public_bytes(encoding, form) != key.public_key().public_bytes(encoding, form):
        raise ValueError("Input identity mismatch")
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()) + cert.public_bytes(serialization.Encoding.PEM)


def validate_request(request):
    if not isinstance(request, dict) or request.get("operation") not in {"status", "stop", "suspend", "configure"}:
        raise ValueError("Unsupported service operation")
    allowed = {"operation", "settings", "identity"} if request["operation"] == "configure" else {"operation"}
    if set(request) != allowed:
        raise ValueError("Unexpected service request fields")
    return request["operation"]
