"""Download only a publisher-authorized ClipBridge release from GitHub."""
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request

from .update_verify import UPDATE_ASSETS, verify_asset, verify_manifest, version_tuple

REPOSITORY = "yhc1001/ClipBridge"
LATEST = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
ASSET_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
MAX_RESPONSE = 1024 * 1024


class TrustedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urllib.parse.urlsplit(newurl)
        if (destination.scheme != "https" or destination.hostname not in ASSET_HOSTS or
                destination.port not in (None, 443) or destination.username or destination.password):
            raise ValueError("Unexpected update download location")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_small(url, *, opener=None):
    client = opener or urllib.request.build_opener(TrustedRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "ClipBridge-Updater", "Accept": "application/json"})
    with client.open(request, timeout=20) as response:
        body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise ValueError("Update metadata is too large")
    return json.loads(body)


def release_url(version, name):
    version_tuple(version)
    if name not in UPDATE_ASSETS and name != "ClipBridge-update.json":
        raise ValueError("Unknown update asset")
    return "https://github.com/" + REPOSITORY + "/releases/download/v" + version + "/" + name


def find_update(installed_version, public_key, *, opener=None):
    latest = read_small(LATEST, opener=opener)
    if not isinstance(latest, dict) or latest.get("draft") is not False or latest.get("prerelease") is not False:
        raise ValueError("Unexpected release")
    tag = latest.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Invalid release tag")
    version = tag[1:]
    if version_tuple(version) <= version_tuple(installed_version):
        return None
    envelope = read_small(release_url(version, "ClipBridge-update.json"), opener=opener)
    verify_manifest(envelope, public_key, installed_version=installed_version, requested_version=version)
    # Keep the signed envelope: the download and privileged installer must
    # independently re-verify it at their own trust boundaries.
    return envelope


def download_asset(envelope, name, destination, *, public_key, installed_version, opener=None):
    # Reverify at the download boundary, even if a caller already displayed an
    # update. This function must never rely on untrusted, mutable metadata.
    manifest = verify_manifest(envelope, public_key, installed_version=installed_version)
    if name not in UPDATE_ASSETS or name not in manifest["assets"]:
        raise ValueError("Update unavailable for this edition")
    entry = manifest["assets"][name]
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    # Caller must choose and protect this directory; never accept an
    # installation or output path from release metadata.
    client = opener or urllib.request.build_opener(TrustedRedirect())
    request = urllib.request.Request(release_url(manifest["version"], name), headers={"User-Agent": "ClipBridge-Updater"})
    fd, filename = tempfile.mkstemp(prefix=".clipbridge-update-", dir=directory)
    path = Path(filename)
    try:
        with os.fdopen(fd, "wb") as output, client.open(request, timeout=30) as response:
            count = 0
            while data := response.read(1024 * 1024):
                count += len(data)
                if count > entry["size"]:
                    raise ValueError("Update file size mismatch")
                output.write(data)
        verify_asset(path, entry)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
