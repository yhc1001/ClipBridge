import base64
import json
import pytest
from clipbridge.config import ConfigStore
from clipbridge.input_engine import defaults
from clipbridge.security import unprotect
from clipbridge.service_policy import canonical_identity, public_settings, validate_request, validate_settings


def test_service_rejects_commands_paths_and_unknown_operations():
    settings = public_settings(defaults())
    assert validate_settings(settings) == settings
    for key in ("engine", "command", "certificate", "protected_identity", "working_directory"):
        with pytest.raises(ValueError):
            validate_settings({**settings, key: "C:/untrusted.exe"})
    for value in ({"operation": "execute", "command": "anything"}, {"operation": "stop", "path": "anything"}, {"operation": "configure"}):
        with pytest.raises(ValueError):
            validate_request(value)
    assert validate_request({"operation": "status"}) == "status"


def test_service_normalizes_identity_and_rejects_mismatched_key(tmp_path):
    config = ConfigStore(tmp_path / "one").load()
    other = ConfigStore(tmp_path / "two").load()
    raw = unprotect(config.protected_key) + config.cert_pem.encode()
    assert canonical_identity(raw) == raw
    with pytest.raises(ValueError):
        canonical_identity(unprotect(other.protected_key) + config.cert_pem.encode())
    with pytest.raises(ValueError):
        canonical_identity(b"x" * 20000)


def test_service_only_accepts_validated_peers_and_screen_options():
    settings = public_settings(defaults())
    settings["enabled"] = True
    with pytest.raises(ValueError):
        validate_settings(settings)
    settings["trusted_clients"] = ["a" * 64]
    assert validate_settings(settings)["enabled"]
    settings["screens"][0]["options"] = {"enterCommand": "anything"}
    with pytest.raises(ValueError):
        validate_settings(settings)
