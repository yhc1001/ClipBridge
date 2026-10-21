"""Real bundled input transport between two isolated virtual X11 desktops.

Never connects to or injects input into the user's desktop. Both X servers are
private Unix-socket-only Xvfb processes created and removed by this test.
"""
import json
import ctypes
import ctypes.util
import os
from pathlib import Path
import select
import socket
import statistics
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


def move_pointer(display, x, y):
    # XWarpPointer (used by xdotool mousemove) does not produce XI2 raw
    # motion. The core listens to raw motion, so use XTest device input.
    x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
    xtst = ctypes.CDLL(ctypes.util.find_library("Xtst"))
    x11.XOpenDisplay.argtypes, x11.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    connection = x11.XOpenDisplay(display.encode())
    if not connection:
        raise RuntimeError("Private test display is unavailable")
    try:
        assert xtst.XTestFakeMotionEvent(connection, -1, x, y, 0)
        x11.XSync(connection, False)
    finally:
        x11.XCloseDisplay(connection)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


application = QCoreApplication([])
processes, logs = [], []
with tempfile.TemporaryDirectory(prefix="ClipBridge-X11-input-") as temporary:
    directory = Path(temporary)
    try:
        displays = [start_display(processes), start_display(processes)]
        configs = [ConfigStore(directory / name).load() for name in ("a", "b")]
        measurements = {"legacy_250ms": [], "default_instant": []}
        for label, delay in (("legacy_250ms", 250), ("default_instant", None)):
            for sample in range(3):
                active, pair_logs = [], []
                move_pointer(displays[0], 300, 240)
                move_pointer(displays[1], 320, 240)
                with socket.socket() as endpoint:
                    endpoint.bind(("127.0.0.1", 0))
                    port = endpoint.getsockname()[1]
                try:
                    for index, (name, mode) in enumerate((("Main", "server"), ("Linux", "client"))):
                        settings = defaults()
                        settings.update(name=name, mode=mode, server_ip="127.0.0.1", port=port,
                            screens=[{"name": "Main", "x": 0, "y": 0}, {"name": "Linux", "x": 1, "y": 0}])
                        if delay is not None:
                            settings["switch_delay"] = delay
                        else:
                            assert settings["switch_delay"] == 0, "Production default must switch immediately"
                        settings["trusted_clients" if index == 0 else "trusted_servers"] = [fingerprint(configs[1-index].cert_pem)]
                        profile_dir = directory / f"{label}-{sample}-{name}"
                        program, arguments, environment = prepare_profile(configs[index], settings, profile_dir)
                        # Only synthetic private desktops emit DEBUG output.
                        profile = QSettings(arguments[2], QSettings.Format.IniFormat)
                        profile.setValue("log/level", "DEBUG")
                        profile.sync()
                        env = {key: environment.value(key) for key in environment.keys()}
                        env.update(DISPLAY=displays[index], QT_QPA_PLATFORM="xcb")
                        env.pop("XAUTHORITY", None)
                        log = directory / f"{label}-{sample}-{name}.txt"
                        logs.append(log)
                        pair_logs.append(log)
                        with log.open("wb") as output:
                            process = subprocess.Popen([program, *arguments], env=env, stdout=output, stderr=subprocess.STDOUT)
                        processes.append(process)
                        active.append(process)
                        if index == 0:
                            wait(lambda: "started server" in log.read_text(errors="replace").lower() or "waiting for clients" in log.read_text(errors="replace").lower())
                    wait(lambda: "connected to server" in pair_logs[1].read_text(errors="replace").lower())
                    # Use an actual client window so keyboard delivery is also
                    # verified after the final default-configured transition.
                    verify_keys = label == "default_instant" and sample == 2
                    if verify_keys:
                        events = directory / "key-events.txt"
                        with events.open("wb") as output:
                            process = subprocess.Popen(["stdbuf", "-oL", "xev", "-display", displays[1], "-event", "keyboard"], stdout=output, stderr=subprocess.STDOUT)
                        processes.append(process)
                        active.append(process)
                        window = wait(lambda: command(displays[1], "search", "--name", "Event Tester"))
                        command(displays[1], "windowfocus", window.splitlines()[0])
                    move_pointer(displays[0], 300, 240)
                    time.sleep(.1)
                    before = command(displays[1], "getmouselocation", "--shell")
                    started = time.monotonic()
                    move_pointer(displays[0], 639, 240)
                    wait(lambda: command(displays[1], "getmouselocation", "--shell") != before)
                    measurements[label].append(round((time.monotonic() - started) * 1000, 2))
                    if verify_keys:
                        command(displays[0], "key", "--clearmodifiers", "a")
                        wait(lambda: "keysym 0x61, a" in events.read_text(errors="replace"))
                finally:
                    for process in reversed(active):
                        stop_process(process)
        old, new = (statistics.median(measurements[key]) for key in ("legacy_250ms", "default_instant"))
        print("SCREEN_SWITCH_BENCHMARK " + json.dumps({**measurements, "legacy_median_ms": old, "instant_median_ms": new,
            "scope": "loopback TLS / two private Xvfb displays; includes polling and process scheduling"}), flush=True)
        assert old >= 180 and new < old - 100, "Removing the configured edge wait must reduce actual transition latency"
        print("Bundled server/client TLS authentication on separate X11 desktops: PASS", flush=True)
        print("Bundled mouse screen transition and keyboard transport into client X11 window: PASS", flush=True)
    except Exception:
        for log in logs:
            print(log.name + ":\n" + log.read_text(errors="replace")[-4000:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            stop_process(process)
