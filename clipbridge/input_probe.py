"""Build-only probe; never starts mouse/keyboard capture or injection."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QProcess
from .input_bundle import bundle_directory, bundled_engine
from .input_engine import defaults, native_library_path, prepare_profile


def probe(config, directory):
    executable = Path(bundled_engine())
    if not executable.is_relative_to(bundle_directory()):
        raise ValueError("Engine did not come from the application bundle")
    with tempfile.TemporaryDirectory(prefix="input-probe-", dir=directory) as temporary:
        settings = defaults()
        settings["engine"] = str(directory / "no-installed-Deskflow/deskflow-core")
        settings["name"] = "ClipBridgeProbe"
        settings["screens"] = [{"name": "ClipBridgeProbe", "x": 0, "y": 0}]
        program, args, environment = prepare_profile(config, settings, Path(temporary))
        process = QProcess()
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        with native_library_path():
            process.start(program, ["--version"])
        if not process.waitForFinished(15000) or process.exitCode() != 0:
            process.kill()
            process.waitForFinished(2000)
            raise RuntimeError("내장 입력 엔진 실행 검사 실패: exit=" + str(process.exitCode()) + ", error=" + process.errorString() + " " + bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")[-2000:])
        if "1.27.0" not in bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace"):
            raise RuntimeError("Bundled engine version mismatch")
    (directory / "input-probe.json").write_text(json.dumps({"bundled": True, "version": "1.27.0", "private_profile_cleaned": not Path(temporary).exists()}), encoding="utf-8")
