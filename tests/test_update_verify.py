"""Update authorization tests use disposable keys and temporary files."""
import base64
import copy
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clipbridge.model import canonical
from clipbridge.update_verify import verify_asset, verify_manifest


@pytest.fixture
def signed():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    manifest = {"schema": 1, "version": "1.7.0", "assets": {
        "ClipBridge-UAC-setup-x64.msi": {"size": 7, "sha256": hashlib.sha256(b"package").hexdigest()}}}
    return public, {"manifest": manifest, "signature": base64.b64encode(key.sign(canonical(manifest))).decode("ascii")}


def test_valid_signed_release_and_exact_file(signed, tmp_path):
    public, envelope = signed
    manifest = verify_manifest(envelope, public, installed_version="1.6.5", requested_version="1.7.0")
    package = tmp_path / "fixture.msi"
    package.write_bytes(b"package")
    verify_asset(package, manifest["assets"]["ClipBridge-UAC-setup-x64.msi"])
    package.write_bytes(b"tampered")
    with pytest.raises(ValueError):
        verify_asset(package, manifest["assets"]["ClipBridge-UAC-setup-x64.msi"])


def test_cannot_tamper_with_asset_version_or_use_another_signing_key(signed):
    public, envelope = signed
    for mutation in ("digest", "version", "extra", "key"):
        candidate = copy.deepcopy(envelope)
        key = public
        if mutation == "digest":
            candidate["manifest"]["assets"]["ClipBridge-UAC-setup-x64.msi"]["sha256"] = "0" * 64
        elif mutation == "version":
            candidate["manifest"]["version"] = "2.0.0"
        elif mutation == "extra":
            candidate["manifest"]["assets"]["untrusted.exe"] = {"size": 1, "sha256": "0" * 64}
        else:
            key = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        with pytest.raises(ValueError):
            verify_manifest(candidate, key, installed_version="1.6.5")


@pytest.mark.parametrize("version", ["1.6.5", "1.6.4", "../1.7.0", "v1.7.0", "1.07.0", "65536.0.0"])
def test_replay_and_invalid_versions_are_rejected(signed, version):
    public, envelope = signed
    envelope["manifest"]["version"] = version
    with pytest.raises(ValueError):
        verify_manifest(envelope, public, installed_version="1.6.5")


def test_latest_release_tag_cannot_be_substituted(signed):
    public, envelope = signed
    with pytest.raises(ValueError):
        verify_manifest(envelope, public, installed_version="1.6.5", requested_version="1.8.0")


def test_publisher_signs_every_edition_and_rejects_missing_file(tmp_path):
    from tools.update_signer import signed_release
    from clipbridge.update_verify import UPDATE_ASSETS
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    for name in UPDATE_ASSETS:
        (tmp_path / name).write_bytes(name.encode())
    envelope = signed_release(key, public, tmp_path, "1.7.0")
    assert set(verify_manifest(envelope, public, installed_version="1.6.5")["assets"]) == UPDATE_ASSETS
    (tmp_path / "ClipBridge.exe").unlink()
    with pytest.raises(FileNotFoundError):
        signed_release(key, public, tmp_path, "1.7.0")


def test_publisher_key_acl_rejects_nonadmin_access():
    import sys
    if sys.platform != "win32":
        pytest.skip("Windows ACL")
    import win32security
    from tools.update_signer import check_descriptor
    good = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", 1)
    check_descriptor(good)
    for sddl in ("O:SYG:SYD:P(A;;FA;;;AU)", "O:SYG:SYD:(A;;FA;;;SY)", "O:BUG:BUD:P(A;;FA;;;SY)"):
        descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1)
        with pytest.raises(PermissionError):
            check_descriptor(descriptor)


def test_real_publisher_key_initialization_denies_restricted_user(tmp_path, monkeypatch):
    # Create an administrator-only key only on an ephemeral CI runner.
    import ctypes
    import os
    import sys
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true" or not ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip("requires a disposable elevated Windows CI runner")
    import pywintypes, win32api, win32con, win32file, win32security
    from tools import update_signer
    folder = tmp_path / "publisher"
    monkeypatch.setattr(update_signer, "PRIVATE_DIRECTORY", folder)
    monkeypatch.setattr(update_signer, "PRIVATE", folder / "key.dpapi")
    monkeypatch.setattr(update_signer, "PUBLIC", tmp_path / "publisher.pub")
    update_signer.initialize()
    update_signer.check_protected(folder)
    update_signer.check_protected(folder / "key.dpapi")
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
    restricted = None
    try:
        admins = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)
        restricted = win32security.CreateRestrictedToken(token, 1, [(admins, 0)], None, None)
        win32security.ImpersonateLoggedOnUser(restricted)
        try:
            try:
                handle = win32file.CreateFile(str(folder / "key.dpapi"), win32con.GENERIC_READ, 0, None,
                                               win32con.OPEN_EXISTING, 0, None)
            except pywintypes.error as error:
                assert error.winerror == 5
            else:
                handle.Close()
                pytest.fail("restricted user could read administrator-only signing key")
        finally:
            win32security.RevertToSelf()
    finally:
        if restricted:
            restricted.Close()
        token.Close()
    before = (folder / "key.dpapi").read_bytes()
    update_signer.initialize()  # Idempotent: never rotate an existing key.
    assert (folder / "key.dpapi").read_bytes() == before
