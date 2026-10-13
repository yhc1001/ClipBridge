"""Run native macOS builds and download their artifacts without leaking credentials."""
import argparse
import io
import json
import sys
from pathlib import Path
import urllib.error
import urllib.request
import zipfile
from github_account_check import github_request, github_token

PREFIX = "/repos/yhc1001/ClipBridge"
sys.stdout.reconfigure(encoding="utf-8")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def download(token, path):
    request = urllib.request.Request("https://api.github.com" + path, headers={"Authorization": "Bearer " + token, "User-Agent": "ClipBridge-builder"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code != 302:
            raise
        destination = error.headers["Location"]
        if not destination.startswith("https://"):
            raise RuntimeError("Unexpected download redirect")
    # Signed artifact URL needs no Authorization header.
    with urllib.request.urlopen(destination, timeout=60) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("dispatch", "status", "logs", "download", "cancel"))
    parser.add_argument("--run", type=int)
    args = parser.parse_args()
    token = github_token()
    if args.action == "dispatch":
        github_request(token, PREFIX + "/actions/workflows/build-macos.yml/dispatches", "POST", {"ref": "main"})
        print("Native macOS workflow dispatched")
        return
    if not args.run:
        runs = github_request(token, PREFIX + "/actions/workflows/build-macos.yml/runs?per_page=3")
        print(json.dumps([{k: run[k] for k in ("id", "status", "conclusion", "html_url", "head_sha")} for run in runs["workflow_runs"]]))
        return
    run = github_request(token, PREFIX + f"/actions/runs/{args.run}")
    if args.action == "cancel":
        if run["status"] != "completed":
            github_request(token, PREFIX + f"/actions/runs/{args.run}/cancel", "POST")
        print("Obsolete build stopped")
        return
    if args.action == "status":
        jobs = github_request(token, PREFIX + f"/actions/runs/{args.run}/jobs")
        print(json.dumps({"status": run["status"], "conclusion": run["conclusion"], "url": run["html_url"],
                          "jobs": [{"name": job["name"], "status": job["status"], "conclusion": job["conclusion"],
                                    "steps": [{"name": step["name"], "status": step["status"], "conclusion": step["conclusion"]} for step in job["steps"]]} for job in jobs["jobs"]]}))
    elif args.action == "logs":
        if run["status"] != "completed":
            jobs = github_request(token, PREFIX + f"/actions/runs/{args.run}/jobs")
            for job in jobs["jobs"]:
                if job["status"] == "completed" and job["conclusion"] != "success":
                    data = download(token, PREFIX + f"/actions/jobs/{job['id']}/logs")
                    print(job["name"] + "\n" + "\n".join(data.decode("utf-8", errors="replace").splitlines()[-90:]))
            return
        data = download(token, PREFIX + f"/actions/runs/{args.run}/logs")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.endswith(".txt") and any(label in name.lower() for label in ("tests", "packaged")):
                    text = archive.read(name).decode("utf-8", errors="replace")
                    print(name + "\n" + "\n".join(text.splitlines()[-40:]))
    else:
        if run["conclusion"] != "success":
            raise RuntimeError("Only completed successful builds can be downloaded")
        artifacts = github_request(token, PREFIX + f"/actions/runs/{args.run}/artifacts")
        root = Path(__file__).resolve().parents[1] / "dist" / "v1.1.0"
        root.mkdir(parents=True, exist_ok=True)
        for artifact in artifacts["artifacts"]:
            data = download(token, PREFIX + f"/actions/artifacts/{artifact['id']}/zip")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    if name in ("ClipBridge-macOS-arm64.zip", "ClipBridge-macOS-intel.zip"):
                        (root / name).write_bytes(archive.read(name))
                        print("Downloaded " + name)


if __name__ == "__main__":
    main()
