"""No real network requests, application restart, installer or user files."""
import base64
import io
import json
import hashlib
import urllib.request

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clipbridge.model import canonical
from clipbridge.update_transport import TrustedRedirect, download_asset, find_update, release_url


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, mapping):
        self.mapping = mapping
        self.urls = []
    def open(self, request, timeout):
        self.urls.append(request.full_url)
        return FakeResponse(self.mapping[request.full_url])


def test_verified_release_download_and_tamper_cleanup(tmp_path):
    from clipbridge.update_transport import LATEST
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    name, data = "ClipBridge.exe", b"authorized test executable"
    signed = {"schema": 1, "version": "1.7.0", "assets": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}}}
    envelope = {"manifest": signed, "signature": base64.b64encode(key.sign(canonical(signed))).decode("ascii")}
    routes = {LATEST: json.dumps({"tag_name": "v1.7.0", "draft": False, "prerelease": False}).encode(),
              release_url("1.7.0", "ClipBridge-update.json"): json.dumps(envelope).encode(),
              release_url("1.7.0", name): data}
    client = FakeOpener(routes)
    manifest = find_update("1.6.5", public, opener=client)
    result = download_asset(envelope, name, tmp_path, public_key=public, installed_version="1.6.5", opener=client)
    assert result.read_bytes() == data
    result.unlink()
    routes[release_url("1.7.0", name)] = b"wrong bytes"
    with pytest.raises(ValueError):
        download_asset(envelope, name, tmp_path, public_key=public, installed_version="1.6.5", opener=client)
    assert not list(tmp_path.iterdir())
    envelope["manifest"]["assets"][name]["sha256"] = hashlib.sha256(b"wrong bytes").hexdigest()
    with pytest.raises(ValueError):
        download_asset(envelope, name, tmp_path, public_key=public, installed_version="1.6.5", opener=client)
    assert not list(tmp_path.iterdir())


def test_redirect_rejects_http_and_unrelated_hosts():
    handler = TrustedRedirect()
    source = urllib.request.Request("https://github.com/yhc1001/ClipBridge/releases/download/v1.7.0/ClipBridge.exe")
    for url in ("http://github.com/unsafe", "https://evil.example/file", "https://github.com@evil.example/file",
                "https://github.com:444/file"):
        with pytest.raises(ValueError):
            handler.redirect_request(source, None, 302, "", {}, url)
