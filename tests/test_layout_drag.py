"""Screen arrangement tests use a fake UI owner, never the live input service."""
import concurrent.futures
import copy
import uuid

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from clipbridge.config import Config
from clipbridge.input_engine import defaults
from clipbridge.input_ui import ComputerTile, InputDialog
from test_portability import pump, qt_app
from test_input_setup import devices, wait


@pytest.fixture
def editor(qt_app):
    class Owner(QWidget):
        def __init__(self):
            super().__init__()
            self.config = Config()
            self.config.input_settings = {**defaults(), "name": "Main", "easy_revision": 1,
                "easy_peers": {str(uuid.uuid4()): {"name": "Laptop"}},
                "screens": [{"name": "Main", "x": 1, "y": 1},
                            {"name": "Laptop", "x": 2, "y": 1},
                            {"name": "Server", "x": 3, "y": 1}]}
            self.input_setup = self
            self.requests = []
            self.failure = None
        def device_addresses(self):
            return []
        def change_layout(self, screens, revision):
            self.requests.append((copy.deepcopy(screens), revision))
            result = concurrent.futures.Future()
            if self.failure:
                result.set_exception(self.failure)
            else:
                result.set_result(None)
            return result
    owner = Owner()
    dialog = InputDialog(owner)
    try:
        yield owner, dialog
    finally:
        dialog.close()
        owner.close()


def positions(dialog):
    return {dialog.table.item(i, 0).text(): (int(dialog.table.item(i, 1).text()),
            int(dialog.table.item(i, 2).text())) for i in range(dialog.table.rowCount())}


def test_drop_onto_occupied_screen_swaps_and_sends_complete_arrangement(editor, qt_app):
    owner, dialog = editor
    dialog.move_screen(1, 3, 1)
    pump(qt_app, lambda: bool(owner.requests))
    assert positions(dialog) == {"Main": (1, 1), "Laptop": (3, 1), "Server": (2, 1)}
    assert {s["name"]: (s["x"], s["y"]) for s in owner.requests[0][0]} == positions(dialog)


def test_failed_layout_send_restores_previously_saved_arrangement(editor, qt_app):
    owner, dialog = editor
    old = positions(dialog)
    owner.failure = ValueError("연결이 끊겼습니다.")
    dialog.move_screen(2, 2, 2)
    pump(qt_app, lambda: "연결이 끊겼습니다" in dialog.status.text())
    assert positions(dialog) == old


def test_invalid_gap_restores_original_without_sending(editor, qt_app):
    owner, dialog = editor
    old = positions(dialog)
    dialog.move_screen(1, 2, 2)
    for _ in range(5):
        qt_app.processEvents()
    assert positions(dialog) == old
    assert not owner.requests
    assert "맞닿" in dialog.status.text()
    dialog.move_screen(2, 2, 2)
    pump(qt_app, lambda: bool(owner.requests))
    assert "맞닿" not in dialog.status.text()


def test_mouse_drag_onto_card_reorders_and_preserves_screen_selection(editor, qt_app):
    owner, dialog = editor
    dialog.resize(700, 600)
    dialog.show()
    qt_app.processEvents()
    tile = next(item for item in dialog.scene.items() if isinstance(item, ComputerTile) and item.name == "Laptop")
    target = next(item for item in dialog.scene.items() if isinstance(item, ComputerTile) and item.name == "Server")
    view = dialog.preview.viewport()
    start = dialog.preview.mapFromScene(tile.sceneBoundingRect().center())
    end = dialog.preview.mapFromScene(target.sceneBoundingRect().center())
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(view.mapToGlobal(end)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view, event)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=end)
    pump(qt_app, lambda: bool(owner.requests))
    assert positions(dialog) == {"Main": (1, 1), "Laptop": (3, 1), "Server": (2, 1)}


@pytest.mark.parametrize("source_index", [0, 1])
def test_ui_swap_propagates_to_all_devices_over_real_tls(devices, qt_app, source_index):
    host, first, second = devices("Main"), devices("Laptop"), devices("Server")
    first.join(host)
    wait(lambda: first.data.get("easy_controller"))
    second.join(host)
    wait(lambda: all(len(device.data["screens"]) == 3 for device in (host, first, second)))
    # Present the real network setup through a fake UI owner; no native input
    # process or user clipboard is started.
    class Owner(QWidget):
        def __init__(self, device):
            super().__init__()
            self.config, self.input_setup = device.config, device.engine
        def device_addresses(self):
            return []
    owner = Owner((host, first)[source_index])
    dialog = InputDialog(owner)
    try:
        before = positions(dialog)
        dialog.move_screen(1, *before["Server"])
        pump(qt_app, lambda: positions(dialog)["Laptop"] == before["Server"])
        wait(lambda: all({item["name"]: (item["x"], item["y"]) for item in device.data["screens"]}
                         == positions(dialog) for device in (host, first, second)))
    finally:
        dialog.close()
        owner.close()
