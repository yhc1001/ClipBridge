"""Exercise real Windows pipe framing/ACL/lifecycle without installing a service."""
import os
import sys
import threading
import uuid
from pathlib import Path
import pytest

if sys.platform != "win32":
    pytest.skip("Windows named-pipe transport", allow_module_level=True)

import win32event
from clipbridge import windows_input_service as broker
from clipbridge import windows_service_client as client
from clipbridge.service_policy import validate_request


def test_real_owner_pipe_roundtrip_and_closed_operations(monkeypatch):
    pipe = r"\\.\pipe\ClipBridgeTest-" + uuid.uuid4().hex
    monkeypatch.setattr(broker, "PIPE", pipe)
    monkeypatch.setattr(client, "PIPE", pipe)
    monkeypatch.setattr(client, "installation", lambda: {"owner": client.current_sid(), "executable": sys.executable})
    verified = []
    def verify(pid, path):
        assert pid == os.getpid() and path == sys.executable
        verified.append(pid)
    monkeypatch.setattr(client, "verify_server", verify)
    class Controller:
        def dispatch(self, request):
            assert validate_request(request) == "status"
            return {"ok": True, "echo": "owner pipe"}
    class Server:
        stop_event = win32event.CreateEvent(None, True, False, None)
    server = Server()
    thread = threading.Thread(target=broker.ClipBridgeInputService.pipe_loop, args=(server, Controller(), client.current_sid()), daemon=True)
    thread.start()
    try:
        assert client.request({"operation": "status"})["echo"] == "owner pipe"
        with pytest.raises(RuntimeError, match="rejected"):
            client.request({"operation": "execute", "command": "not allowed"})
        assert len(verified) == 2
    finally:
        win32event.SetEvent(server.stop_event)
        thread.join(timeout=5)
        assert not thread.is_alive(), "Overlapped pipe server did not stop"
        server.stop_event.Close()
