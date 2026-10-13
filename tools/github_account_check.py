"""Inspect GitHub access without displaying or persisting the credential."""
import json
import os
import subprocess
import urllib.error
import urllib.request


def github_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    result = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", text=True,
                            encoding="utf-8", capture_output=True, timeout=25,
                            env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never"))
    if result.returncode:
        raise RuntimeError("GitHub authentication is not available in Git Credential Manager.")
    credential = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = credential.get("password")
    if not token:
        raise RuntimeError("GitHub authentication is not available.")
    return token


def github_request(token, path, method="GET", data=None, headers=None):
    request = urllib.request.Request("https://api.github.com" + path,
                                     data=None if data is None else json.dumps(data).encode("utf-8"), method=method,
                                     headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                                              "User-Agent": "ClipBridge-publisher", "X-GitHub-Api-Version": "2022-11-28",
                                              "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


if __name__ == "__main__":
    try:
        token = github_token()
        user = github_request(token, "/user")
        print(json.dumps({"authenticated": True, "login": user["login"], "profile": user["html_url"]}))
    except (RuntimeError, urllib.error.HTTPError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"authenticated": False, "error_type": type(error).__name__}))
        raise SystemExit(1)
