import asyncio
import base64
import io
import struct
import uuid

import pytest
from PIL import Image

from clipbridge.config import ConfigStore
from clipbridge.files import ReceiveTransfer, scan_sources, validate_manifest
from clipbridge.images import dib_image, image_formats, normalize
from clipbridge.model import Ledger, Snapshot, Stamp, private_address, safe_relative
from clipbridge.network import read_frame
from clipbridge.security import fingerprint, pairing_token, parse_pairing, proof, protect, unprotect


@pytest.mark.parametrize("address", ["192.168.1.2", "10.0.0.8", "172.16.4.5", "100.77.2.3", "127.0.0.1", "fd7a:115c:a1e0::1"])
def test_lan_addresses(address):
    assert private_address(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "0.0.0.0", "224.0.0.1", "example.com", "172.32.1.1", "100.1.1.1", "2001:4860:4860::8888"])
def test_external_addresses_blocked(address):
    with pytest.raises(ValueError):
        private_address(address)


@pytest.mark.parametrize("path", ["../x", "/abs", "C:/file", "a\\b", "CON", "a/NUL.txt", "a/COM1", "a.", "a ", "a//b", "a\0b", "a:stream", "a/LPT¹.txt"])
def test_path_attacks_blocked(path):
    with pytest.raises(ValueError):
        safe_relative(path)


def test_conflict_converges_without_wall_clock():
    a, b = Ledger(str(uuid.UUID(int=1))), Ledger(str(uuid.UUID(int=2)))
    first, second = a.local(), b.local()
    assert a.claim(second)
    assert not b.claim(first)
    assert a.latest == b.latest
    next_a = a.local()
    assert b.claim(next_a)
    assert not b.claim(next_a)


def test_digest_and_utf8():
    snapshot = Snapshot({"text": "한글 / 😀 / 日本語".encode(), "HTML Format": b"<b>Hello</b>"})
    decoded = Snapshot.decode(snapshot.wire())
    assert snapshot.digest() == decoded.digest()
    assert Snapshot(dict(reversed(list(snapshot.formats.items())))).digest() == snapshot.digest()
    with pytest.raises(ValueError):
        Snapshot.decode({"private format": "YQ=="})
    with pytest.raises(ValueError):
        Snapshot.decode({"text": base64.b64encode(b"x" * 50).decode()}, limit=10)
    with pytest.raises(ValueError):
        Snapshot.decode({"text": "/w=="})


def test_images_validate_and_preserve_multiple_formats():
    formats = image_formats(Image.new("RGBA", (24, 18), (20, 60, 90, 128)))
    assert dib_image(formats["DIB"]).size == (24, 18)
    assert dib_image(formats["DIBV5"]).getpixel((0, 0)) == (20, 60, 90, 128)
    assert normalize(formats, 100000, incoming=True) == formats
    assert set(normalize({"PNG": formats["PNG"]}, 100000)) == {"PNG", "DIB", "DIBV5"}
    with pytest.raises(ValueError):
        normalize({"DIB": formats["DIB"][:40]}, 100000, incoming=True)


def test_dpapi_pairing_and_auth_transcript(tmp_path):
    config = ConfigStore(tmp_path).load()
    device, pin, secret = parse_pairing(pairing_token(config))
    assert (device, pin, secret) == (config.device_id, fingerprint(config.cert_pem), config.secret)
    assert unprotect(protect(b"secret")) == b"secret"
    a = proof(secret, "client", device, str(uuid.uuid4()), "a" * 64, "b" * 64)
    assert a != proof(secret, "server", device, str(uuid.uuid4()), "a" * 64, "b" * 64)
    assert ConfigStore(tmp_path).load().device_id == device


def test_file_directory_transfer_and_integrity(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "한글.txt").write_text("테스트", encoding="utf-8")
    (source / "empty-dir").mkdir()
    (source / "zero").touch()
    other = tmp_path / "other.bin"
    other.write_bytes(bytes(range(256)) * 2000)
    manifest, sources = scan_sources([str(source), str(other)], 1024**2)
    validate_manifest(manifest, 1024**2)
    parent = tmp_path / "received"
    parent.mkdir()
    transfer = ReceiveTransfer(parent, str(uuid.uuid4()), manifest)
    for name, path in sources.items():
        data = path.read_bytes()
        for offset in range(0, len(data), 256 * 1024):
            transfer.chunk(name, offset, data[offset:offset + 256 * 1024])
    roots = transfer.finish()
    assert len(roots) == 2
    assert (transfer.directory / "source" / "한글.txt").read_text(encoding="utf-8") == "테스트"
    assert (transfer.directory / "source" / "empty-dir").is_dir()
    assert (transfer.directory / "other.bin").read_bytes() == other.read_bytes()
    transfer.remove()
    assert not transfer.directory.exists()


def test_file_limits_hash_and_manifest_collisions(tmp_path):
    source = tmp_path / "data"
    source.write_bytes(b"123")
    with pytest.raises(ValueError):
        scan_sources([str(source)], 2)
    manifest, _ = scan_sources([str(source)], 10)
    transfer = ReceiveTransfer(tmp_path, str(uuid.uuid4()), manifest)
    with pytest.raises(ValueError):
        transfer.chunk("data", 1, b"1")
    transfer.chunk("data", 0, b"456")
    with pytest.raises(ValueError):
        transfer.finish()
    transfer.remove()
    manifest["entries"].append(dict(manifest["entries"][0], path="DATA"))
    with pytest.raises(ValueError):
        validate_manifest(manifest, 10)


def test_oversized_frames_rejected_before_allocation():
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!I", 10000))
        with pytest.raises(ValueError):
            await read_frame(reader, limit=100)
    asyncio.run(run())
