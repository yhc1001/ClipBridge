"""No live input hooks: verify fresh and upgraded handoff preferences."""
import json
import uuid

import pytest

from clipbridge.config import ConfigStore
from clipbridge.input_engine import defaults


def test_fresh_mouse_setup_has_no_edge_wait():
    assert defaults()["switch_delay"] == 0


@pytest.mark.parametrize("unified,delay,expected", [(True, 250, 0), (True, 0, 0), (True, 500, 500), (False, 250, 250)])
def test_old_default_wait_migrates_once_without_losing_custom_preferences(tmp_path, unified, delay, expected):
    store = ConfigStore(tmp_path)
    config = store.load()
    config.input_settings = {**defaults(), "switch_delay": delay}
    if unified:
        config.input_settings["easy_controller"] = str(uuid.uuid4())
    store.save(config)
    old = json.loads(store.path.read_text(encoding="utf-8"))
    old.pop("input_defaults_version")
    store.path.write_text(json.dumps(old), encoding="utf-8")
    updated = store.load()
    assert updated.input_settings["switch_delay"] == expected
    # A subsequent explicit choice is respected on later launches.
    updated.input_settings["switch_delay"] = 250
    store.save(updated)
    assert store.load().input_settings["switch_delay"] == 250
