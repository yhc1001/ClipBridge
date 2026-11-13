"""Initialize an administrator-protected publisher key and sign release metadata.

Run on the publisher's Windows PC as administrator. The private key never
belongs in a release archive, Git repository, update packet or CI log.
"""
import argparse
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clipbridge import __version__
from clipbridge.model import canonical
from clipbridge.security import protect, unprotect
from clipbridge.update_verify import UPDATE_ASSETS, verify_manifest

PUBLIC = ROOT / "assets" / "update-publisher.pub"
PRIVATE_DIRECTORY = Path(os.environ.get("PROGRAMDATA", "")) / "ClipBridgePublisher"
PRIVATE = PRIVATE_DIRECTORY / "release-key.dpapi"


def ensure_administrator():
    if sys.platform != "win32" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError("Windows 관리자 권한이 필요합니다.")


def secured_attributes():
    import pywintypes, win32security
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", 1)
    return attributes


def check_descriptor(descriptor):
    import win32security
    owner = win32security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
    if owner not in ("S-1-5-18", "S-1-5-32-544"):
        raise PermissionError("Publisher key is not administrator owned")
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None:
        raise PermissionError("Publisher key has no protected ACL")
    for index in range(acl.GetAceCount()):
        ace = acl.GetAce(index)
        if ace[0][0] != 0 or win32security.ConvertSidToStringSid(ace[2]) not in ("S-1-5-18", "S-1-5-32-544"):
            raise PermissionError("Publisher key grants access to a non-administrator")
    if not (descriptor.GetSecurityDescriptorControl()[0] & 0x1000):
        raise PermissionError("Publisher key ACL is not protected")


def check_protected(path):
    import stat, win32security
    from clipbridge.files import assert_local_regular
    info = assert_local_regular(path)
    if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise PermissionError("Unsafe publisher key path")
    descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
    check_descriptor(descriptor)


def initialize():
    import win32con, win32file, win32security
    ensure_administrator()
    if not PRIVATE_DIRECTORY.exists():
        win32file.CreateDirectory(str(PRIVATE_DIRECTORY), secured_attributes())
    check_protected(PRIVATE_DIRECTORY)
    if PRIVATE.exists():
        check_protected(PRIVATE)
        existing = Ed25519PrivateKey.from_private_bytes(unprotect(PRIVATE.read_text(encoding="ascii")))
        public = existing.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        print("기존 공개 키: " + public.hex())
        return
    if PUBLIC.exists():
        raise FileExistsError("기존 공개 키가 있습니다. 새 키로 덮어쓰지 않습니다.")
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    encrypted = protect(private).encode("ascii")
    handle = win32file.CreateFile(str(PRIVATE), win32con.GENERIC_WRITE, 0, secured_attributes(),
                                  win32con.CREATE_NEW, win32con.FILE_ATTRIBUTE_NORMAL, None)
    try:
        descriptor = win32security.GetSecurityInfo(handle, win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
        check_descriptor(descriptor)
        win32file.WriteFile(handle, encrypted)
        win32file.FlushFileBuffers(handle)
    finally:
        handle.Close()
    check_protected(PRIVATE)
    print("서명 키를 생성했습니다. 공개 키만 프로그램에 포함됩니다: " + public.hex())


def sign_release():
    import win32con, win32file, win32security
    ensure_administrator()
    check_protected(PRIVATE_DIRECTORY)
    check_protected(PRIVATE)
    key = Ed25519PrivateKey.from_private_bytes(unprotect(PRIVATE.read_text(encoding="ascii")))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if public.hex() != PUBLIC.read_text(encoding="ascii").strip():
        raise ValueError("Publisher public key does not match")
    directory = ROOT / "dist" / ("v" + __version__)
    envelope = signed_release(key, public, directory, __version__)
    # Elevated code never writes to the user's writable checkout/release
    # directory. A normal user can copy this signed result after inspection.
    output = PRIVATE_DIRECTORY / ("ClipBridge-update-v" + __version__ + ".json")
    handle = win32file.CreateFile(str(output), win32con.GENERIC_WRITE, 0, secured_attributes(),
                                  win32con.CREATE_NEW, win32con.FILE_ATTRIBUTE_NORMAL, None)
    try:
        descriptor = win32security.GetSecurityInfo(handle, win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
        check_descriptor(descriptor)
        data = json.dumps(envelope, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        win32file.WriteFile(handle, data)
        win32file.FlushFileBuffers(handle)
    finally:
        handle.Close()
    check_protected(output)
    print("서명된 업데이트 정보가 관리자 보호 폴더에 준비됐습니다.")


def signed_release(key, public, directory, version):
    from clipbridge.files import assert_local_regular
    assets = {}
    for name in sorted(UPDATE_ASSETS):
        path = directory / name
        before = assert_local_regular(path)
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as stream:
            while data := stream.read(1024 * 1024):
                digest.update(data)
                count += len(data)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != before.st_size:
            raise ValueError("Release file changed while signing")
        assets[name] = {"size": count, "sha256": digest.hexdigest()}
    manifest = {"schema": 1, "version": version, "assets": assets}
    envelope = {"manifest": manifest, "signature": base64.b64encode(key.sign(canonical(manifest))).decode("ascii")}
    verify_manifest(envelope, public, installed_version="0.0.0", requested_version=version)
    return envelope


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", "sign"))
    action = parser.parse_args().action
    initialize() if action == "init" else sign_release()
