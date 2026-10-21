"""Real bundled input transport between two isolated virtual X11 desktops.

Never connects to or injects input into the user's desktop. Both X servers are
private Unix-socket-only Xvfb processes created and removed by this test.
"""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import time

if not sys.platform.startswith("linux"):
    raise SystemExit("This integration test requires Linux Xvfb")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QSettings
from clipbridge.config import ConfigStore
from clipbridge.input_engine import defaults, prepare_profile
from clipbridge.security import fingerprint


def wait(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = predicate()
        except subprocess.CalledProcessError:
            value = False
        if value:
            return value
        time.sleep(.05)
    raise RuntimeError("Virtual input integration timed out")


def start_display(processes):
    reader, writer = os.pipe()
    try:
        process = subprocess.Popen(["Xvfb", "-displayfd", str(writer), "-screen", "0", "640x480x24", "-ac", "-nolisten", "tcp"],
            pass_fds=(writer,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(process)
        if not select.select([reader], [], [], 10)[0]:
            raise RuntimeError("Virtual display did not start")
        return ":" + os.read(reader, 100).decode().strip()
    finally:
        os.close(reader)
        os.close(writer)


def command(display, *arguments):
    return subprocess.check_output(["xdotool", *arguments], env=dict(os.environ, DISPLAY=display), text=True, timeout=8).strip()


application = QCoreApplication([])
processes, logs = [], []
with tempfile.TemporaryDirectory(prefix="ClipBridge-X11-input-") as temporary:
    directory = Path(temporary)
    try:
        displays = [start_display(processes), start_display(processes)]
        configs = [ConfigStore(directory / name).load() for name in ("a", "b")]
        with socket.socket() as endpoint:
            endpoint.bind(("127.0.0.1", 0))
            port = endpoint.getsockname()[1]
        for index, (name, mode) in enumerate((("Main", "server"), ("Linux", "client"))):
            settings = defaults()
            settings.update(name=name, mode=mode, server_ip="127.0.0.1", port=port, switch_delay=0,
                screens=[{"name": "Main", "x": 0, "y": 0}, {"name": "Linux", "x": 1, "y": 0}])
            settings["trusted_clients" if index == 0 else "trusted_servers"] = [fingerprint(configs[1-index].cert_pem)]
            program, arguments, environment = prepare_profile(configs[index], settings, directory / ("native-" + name))
            # Upstream emits server readiness and client connection at DEBUG.
            # Keep verbose output confined to this disposable test profile.
            profile = QSettings(arguments[2], QSettings.Format.IniFormat)
            profile.setValue("log/level", "DEBUG")
            profile.sync()
            env = {key: environment.value(key) for key in environment.keys()}
            env.update(DISPLAY=displays[index], QT_QPA_PLATFORM="xcb")
            env.pop("XAUTHORITY", None)
            log = directory / (name + ".txt")
            logs.append(log)
            with log.open("wb") as output:
                processes.append(subprocess.Popen([program, *arguments], env=env, stdout=output, stderr=subprocess.STDOUT))
            if index == 0:
                wait(lambda: "started server" in log.read_text(errors="replace").lower() or "waiting for clients" in log.read_text(errors="replace").lower())
        wait(lambda: "connected to server" in logs[1].read_text(errors="replace").lower())
        print("Bundled server/client TLS authentication on separate X11 desktops: PASS", flush=True)
        events = directory / "key-events.txt"
        with events.open("wb") as output:
            processes.append(subprocess.Popen(["xev", "-display", displays[1], "-event", "keyboard"], stdout=output, stderr=subprocess.STDOUT))
        window = wait(lambda: command(displays[1], "search", "--name", "Event Tester"))
        command(displays[1], "windowfocus", window.splitlines()[0])
        command(displays[0], "mousemove", "300", "240")
        before = command(displays[1], "getmouselocation", "--shell")
        command(displays[0], "mousemove", "639", "240")
        wait(lambda: command(displays[1], "getmouselocation", "--shell") != before)
        command(displays[0], "key", "--clearmodifiers", "a")
        wait(lambda: "keysym 0x61, a" in events.read_text(errors="replace"))
        print("Bundled mouse screen transition and keyboard transport into client X11 window: PASS", flush=True)
    except Exception:
        for log in logs:
            print(log.name + ":\n" + log.read_text(errors="replace")[-4000:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
