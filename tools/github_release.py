"""Create a private repository or publish assets to the user's existing repository.

Authentication stays in Git Credential Manager/environment and is never written.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from github_account_check import github_request, github_token


def repository(token, owner, name, create=False):
    path = f"/repos/{owner}/{name}"
    try:
        result = github_request(token, path)
    except urllib.error.HTTPError as error:
        if error.code != 404 or not create:
            raise
        result = github_request(token, "/user/repos", "POST", {
            "name": name, "description": "ClipBridge — Windows PC 간 암호화된 양방향 클립보드 동기화",
            "private": True, "auto_init": False, "has_wiki": False,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "create", "release", "verify"))
    parser.add_argument("--name", default="ClipBridge")
    parser.add_argument("--tag", default="v1.0.0")
    parser.add_argument("--notes", type=Path)
    args = parser.parse_args()
    if not args.name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid repository name")
    token = github_token()
    user = github_request(token, "/user")
    owner = user["login"]
    try:
        repo = repository(token, owner, args.name, create=args.action == "create")
    except urllib.error.HTTPError as error:
        if args.action == "inspect" and error.code == 404:
            print(json.dumps({"exists": False, "owner": owner, "name": args.name}))
            return
        raise
    if args.action in ("inspect", "create"):
        print(json.dumps({"exists": True, "name": repo["full_name"], "private": repo["private"],
                          "url": repo["html_url"], "size": repo["size"], "default_branch": repo["default_branch"]}))
        return
    if repo["owner"]["login"].casefold() != owner.casefold():
        raise RuntimeError("Release repository must belong to the signed-in user.")
    prefix = f"/repos/{repo['full_name']}"
    try:
        release = github_request(token, prefix + "/releases/tags/" + urllib.parse.quote(args.tag, safe=""))
    except urllib.error.HTTPError as error:
        if error.code != 404 or args.action != "release":
            raise
        if not args.notes:
            raise ValueError("Provide --notes for a new release")
        release = github_request(token, prefix + "/releases", "POST", {
            "tag_name": args.tag, "target_commitish": "main", "name": "ClipBridge " + args.tag,
            "body": args.notes.read_text(encoding="utf-8"), "draft": True, "prerelease": False,
        })
    root = Path(__file__).resolve().parents[1]
    dist = root / "dist" / args.tag
    if not dist.exists():
        dist = root / "dist"
    assets = ["ClipBridge.exe", "ClipBridge-portable.zip", "ClipBridge-source.zip", "SHA256SUMS.txt"]
    assets += [name for name in ("ClipBridge-macOS-arm64.zip", "ClipBridge-macOS-intel.zip", "ClipBridge-linux-x86_64.tar.gz", "ClipBridge-input-sources.zip") if (dist / name).exists()]
    if args.action == "release":
        existing = {asset["name"]: asset for asset in release["assets"]}
        upload_base = release["upload_url"].split("{", 1)[0]
        if urllib.parse.urlparse(upload_base).hostname != "uploads.github.com":
            raise RuntimeError("Unexpected upload destination")
        for name in assets:
            path = dist / name
            data = path.read_bytes()
            digest = "sha256:" + hashlib.sha256(data).hexdigest()
            if name in existing:
                if existing[name]["size"] != len(data) or existing[name].get("digest") not in (None, digest):
                    raise RuntimeError("Existing release asset differs: " + name)
                continue
            url = upload_base + "?" + urllib.parse.urlencode({"name": name})
            content_type = "application/zip" if name.endswith(".zip") else "text/plain" if name.endswith(".txt") else "application/octet-stream"
            request = urllib.request.Request(url, data=data, method="POST", headers={
                "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                "User-Agent": "ClipBridge-publisher", "Content-Type": content_type,
                "X-GitHub-Api-Version": "2022-11-28",
            })
            with urllib.request.urlopen(request, timeout=120) as response:
                asset = json.load(response)
            if asset["size"] != len(data) or asset.get("digest") not in (None, digest):
                raise RuntimeError("Upload verification failed: " + name)
            print("Uploaded " + name, flush=True)
        if release["draft"]:
            release = github_request(token, prefix + f"/releases/{release['id']}", "PATCH", {"draft": False})
    release = github_request(token, prefix + f"/releases/{release['id']}")
    remote_assets = {asset["name"]: asset for asset in release["assets"]}
    checked = []
    for name in assets:
        path = dist / name
        expected = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        asset = remote_assets[name]
        if asset["state"] != "uploaded" or asset["size"] != path.stat().st_size or asset.get("digest") not in (None, expected):
            raise RuntimeError("Release verification failed: " + name)
        checked.append({"name": name, "size": asset["size"], "sha256_verified": asset.get("digest") == expected})
    print(json.dumps({"repository": repo["html_url"], "private": repo["private"], "release": release["html_url"],
                      "published": not release["draft"], "assets": checked}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        print("GitHub API HTTP " + str(error.code))
        raise SystemExit(1)
