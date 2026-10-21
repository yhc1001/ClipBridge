import json
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QCoreApplication
from clipbridge import input_bundle
from clipbridge.config import ConfigStore
from clipbridge.input_engine import defaults, identity_pin, migrate_identity, prepare_profile
from clipbridge.security import unprotect
from test_portability import qt_app


def test_bundle_discovery_ignores_system_installation(monkeypatch, tmp_path):
    import hashlib
    engine = tmp_path / "deskflow-core"
    engine.write_bytes(b"native component")
    (tmp_path / "bundle.json").write_text(json.dumps({"executable": engine.name, "hashes": {engine.name: hashlib.sha256(engine.read_bytes()).hexdigest()}}))
    monkeypatch.setattr(input_bundle, "bundle_directory", lambda: tmp_path)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "not-installed"))
    monkeypatch.setenv("PATH", "")
    assert input_bundle.bundled_engine() == str(engine.absolute())
    engine.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="손상"):
        input_bundle.bundled_engine()


def test_imported_identity_survives_removing_original_installation(qt_app, tmp_path):
    config = ConfigStore(tmp_path / "config").load()
    path = tmp_path / "old-install/identity.pem"
    path.parent.mkdir()
    path.write_bytes(unprotect(config.protected_key) + config.cert_pem.encode())
    settings = defaults()
    settings["certificate"] = str(path)
    pin = identity_pin(config, settings)
    assert migrate_identity(settings)
    path.unlink()
    assert settings["certificate"] == "" and settings["protected_identity"]
    assert identity_pin(config, settings) == pin
    config.input_settings = settings
    ConfigStore(tmp_path / "config").save(config)
    assert identity_pin(config, ConfigStore(tmp_path / "config").load().input_settings) == pin


def test_shipped_engine_probe_without_installed_deskflow(qt_app, tmp_path, monkeypatch):
    if not input_bundle.bundled_engine():
        pytest.skip("Prepare bundled input component before this integration check")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "not-installed"))
    from clipbridge.input_probe import probe
    config = ConfigStore(tmp_path / "probe").load()
    probe(config, tmp_path / "probe")
    assert json.loads((tmp_path / "probe/input-probe.json").read_text())["private_profile_cleaned"]
