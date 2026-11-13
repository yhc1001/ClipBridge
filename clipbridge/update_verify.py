"""Verify a publisher-signed update manifest before any file can be installed."""
import base64
import hashlib
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .model import canonical

MAX_UPDATE_BYTES = 1024 * 1024 * 1024
UPDATE_ASSETS = frozenset({
    "ClipBridge.exe", "ClipBridge-UAC-setup-x64.msi",
    "ClipBridge-macOS-arm64.zip", "ClipBridge-macOS-intel.zip",
    "ClipBridge-linux-x86_64.tar.gz",
})


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})", value):
        raise ValueError("Invalid update version")
    parts = tuple(map(int, value.split(".")))
    if any(part > 65535 for part in parts):
        raise ValueError("Invalid update version")
    return parts


def verify_manifest(envelope, public_key, *, installed_version, requested_version=None):
    if not isinstance(envelope, dict) or set(envelope) != {"manifest", "signature"}:
        raise ValueError("Invalid signed update")
    manifest, signature = envelope["manifest"], envelope["signature"]
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "version", "assets"} or
            type(manifest["schema"]) is not int or manifest["schema"] != 1):
        raise ValueError("Invalid update manifest")
    version = version_tuple(manifest["version"])
    if version <= version_tuple(installed_version) or (requested_version is not None and manifest["version"] != requested_version):
        raise ValueError("Update version is not newer or does not match")
    assets = manifest["assets"]
    if not isinstance(assets, dict) or not assets or len(assets) > len(UPDATE_ASSETS) or not set(assets) <= UPDATE_ASSETS:
        raise ValueError("Invalid update assets")
    for entry in assets.values():
        if (not isinstance(entry, dict) or set(entry) != {"size", "sha256"} or
                type(entry["size"]) is not int or not 0 < entry["size"] <= MAX_UPDATE_BYTES or
                not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise ValueError("Invalid update asset metadata")
    if not isinstance(signature, str) or len(signature) != 88:
        raise ValueError("Invalid update signature")
    try:
        signed = base64.b64decode(signature, validate=True)
        if len(signed) != 64:
            raise ValueError("Invalid update signature")
        Ed25519PublicKey.from_public_bytes(public_key).verify(signed, canonical(manifest))
    except (InvalidSignature, ValueError, TypeError):
        raise ValueError("Update signature verification failed") from None
    return manifest


def verify_asset(path, entry):
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            count += len(data)
            if count > entry["size"]:
                raise ValueError("Update file size mismatch")
            digest.update(data)
    if count != entry["size"] or digest.hexdigest() != entry["sha256"]:
        raise ValueError("Update file integrity mismatch")
