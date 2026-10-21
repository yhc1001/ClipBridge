"""IP-only input enrollment and shared layout; private TLS, explicit approval.

The native input identity signs a fresh, server-certificate-bound challenge.
Unknown devices require local approval; remembered devices must keep their pin.
This channel carries configuration only, never commands or input events.
"""
import asyncio
import base64
import concurrent.futures
import copy
import hashlib
import secrets
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from .input_engine import SETUP_PORT, computer_name, defaults, validate
from .model import canonical, private_address, valid_id
from .network import read_frame, write_frame
from .security import client_context, fingerprint, protect, server_context, unprotect

PROTOCOL = "ClipBridge-input-setup-1"


def settings(config):
    return {**defaults(), **copy.deepcopy(config.input_settings)}


def identity(config):
    value = settings(config)
    raw = unprotect(value["protected_identity"]) if value.get("protected_identity") else unprotect(config.protected_key) + config.cert_pem.encode()
    cert = x509.load_pem_x509_certificate(raw)
    key = serialization.load_pem_private_key(raw, None)
    return cert, key


def certificate_pin(cert):
    return cert.fingerprint(hashes.SHA256()).hex()


def signature(key, value):
    if isinstance(key, ec.EllipticCurvePrivateKey):
        return key.sign(value, ec.ECDSA(hashes.SHA256()))
    if isinstance(key, rsa.RSAPrivateKey) and 2048 <= key.key_size <= 4096:
        return key.sign(value, padding.PKCS1v15(), hashes.SHA256())
    raise ValueError("Unsupported input identity")


def verify_signature(cert, value, signed):
    key = cert.public_key()
    if isinstance(key, ec.EllipticCurvePublicKey):
        key.verify(signed, value, ec.ECDSA(hashes.SHA256()))
    elif isinstance(key, rsa.RSAPublicKey) and 2048 <= key.key_size <= 4096:
        key.verify(signed, value, padding.PKCS1v15(), hashes.SHA256())
    else:
        raise ValueError("Unsupported input identity")


def transcript(challenge, device, name, nonce, pin, client_pin):
    return canonical([PROTOCOL, challenge, valid_id(device), computer_name(name), nonce, pin, client_pin])


def confirmation(value):
    return f"{int.from_bytes(hashlib.sha256(value).digest()[:4], 'big') % 1000000:06d}"


def place_screen(screens, name):
    if any(item["name"] == name for item in screens):
        return screens
    if len(screens) >= 17:
        raise ValueError("화면은 최대 17대까지 연결할 수 있습니다.")
    occupied = {(item["x"], item["y"]) for item in screens}
    for item in screens:
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            x, y = item["x"] + dx, item["y"] + dy
            if 0 <= x <= 8 and 0 <= y <= 8 and (x, y) not in occupied:
                return screens + [{"name": name, "x": x, "y": y}]
    raise ValueError("화면 배치에 빈자리가 없습니다.")


def layout_settings(current, screens):
    if not isinstance(screens, list) or {item.get("name") for item in screens if isinstance(item, dict)} != {item["name"] for item in current["screens"]}:
        raise ValueError("화면 목록이 변경되었습니다. 최신 배치를 확인하세요.")
    previous = {item["name"]: item for item in current["screens"]}
    result = copy.deepcopy(current)
    result["screens"] = []
    for item in screens:
        if not isinstance(item, dict) or set(item) != {"name", "x", "y"}:
            raise ValueError("Invalid screen layout")
        result["screens"].append({**previous[item["name"]], "x": item["x"], "y": item["y"]})
    # Clients display the same complete topology; validate connectivity as a server.
    check = {**result, "mode": "server", "name": result["screens"][0]["name"]}
    validate(check)
    return result


class InputSetup(threading.Thread):
    def __init__(self, config, apply_settings, notify, approve, *, bind="0.0.0.0", port=SETUP_PORT):
        super().__init__(name="ClipBridge-input-setup", daemon=True)
        self.config, self.apply_settings, self.notify, self.approve = config, apply_settings, notify, approve
        self.bind, self.port = private_address(bind, bind=True), port
        self.ready, self.stopped, self.stop_requested = threading.Event(), threading.Event(), threading.Event()
        self.loop = None
        self.clients = {}
        self.pending = 0
        self.client_writer = None
        self.client_task = None
        self.last_error = None

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event, self.lock = asyncio.Event(), asyncio.Lock()
        try:
            self.loop.run_until_complete(self._run())
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self.last_error = type(error).__name__
            self.notify("input_setup_status", "연결 요청을 받을 수 없습니다. ClipBridge 중복 실행·포트 24802를 확인하세요.")
        finally:
            self.ready.set()
            for task in asyncio.all_tasks(self.loop):
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(self.loop), return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
            self.loop.close()
            self.stopped.set()

    async def _run(self):
        if self.stop_requested.is_set():
            return
        cert, self.key = identity(self.config)
        self.cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        self.pin = certificate_pin(cert)
        private = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        context = server_context(self.cert_pem, protect(private))
        server = await asyncio.start_server(self._accept, None if self.bind == "0.0.0.0" else self.bind, self.port, ssl=context,
            ssl_handshake_timeout=5, ssl_shutdown_timeout=1, backlog=8)
        self.port = server.sockets[0].getsockname()[1]
        self.ready.set()
        value = settings(self.config)
        if value.get("easy_controller"):
            self.client_task = asyncio.create_task(self._connect(value["server_ip"], value.get("easy_setup_port", SETUP_PORT)))
        else:
            self.notify("input_setup_status", "연결 요청 대기 중 · 다른 PC에서 이 PC의 IP를 입력하세요.")
        async with server:
            await self.stop_event.wait()

    async def _apply(self, value, show=False, clipboard=None):
        validate(value)
        result = self.apply_settings(value, show, clipboard)
        if isinstance(result, concurrent.futures.Future):
            await asyncio.wrap_future(result)
        elif asyncio.iscoroutine(result):
            await result

    async def _ask(self, info, reader):
        future = concurrent.futures.Future()
        self.approve("input_pair", info, future)
        disconnected = asyncio.create_task(reader.read(1))
        approved = asyncio.wrap_future(future)
        try:
            done, _ = await asyncio.wait((approved, disconnected), timeout=120, return_when=asyncio.FIRST_COMPLETED)
            return bool(approved.result()) if approved in done and disconnected not in done else False
        finally:
            disconnected.cancel()
            await asyncio.gather(disconnected, return_exceptions=True)
            if not future.done():
                future.cancel()

    async def _accept(self, reader, writer):
        counted = False
        device = None
        try:
            address = private_address(writer.get_extra_info("peername")[0])
            if self.pending >= 4 or len(self.clients) >= 16:
                return
            self.pending += 1
            counted = True
            challenge = {"type": "challenge", "protocol": PROTOCOL, "device": self.config.device_id, "nonce": secrets.token_hex(32)}
            await write_frame(writer, challenge)
            request = await read_frame(reader, 16384, timeout=8)
            if set(request) != {"type", "device", "name", "nonce", "certificate", "signature"} or request["type"] != "join":
                raise ValueError("Unexpected setup request")
            device = valid_id(request["device"])
            if device == self.config.device_id:
                raise ValueError("이 컴퓨터 자신의 IP입니다. Main PC의 IP를 입력하세요.")
            name = computer_name(request["name"])
            if not isinstance(request["nonce"], str) or len(request["nonce"]) != 64:
                raise ValueError("Invalid nonce")
            cert = x509.load_pem_x509_certificate(request["certificate"].encode("ascii"))
            pin = certificate_pin(cert)
            if pin == self.pin:
                raise ValueError("이 PC와 같은 인증서입니다. 각 PC의 ClipBridge 설정을 따로 만드세요.")
            proof = transcript(challenge, device, name, request["nonce"], self.pin, pin)
            verify_signature(cert, proof, base64.b64decode(request["signature"], validate=True))
            async with self.lock:
                value = settings(self.config)
                if value.get("easy_controller") or value["mode"] == "client" and value["enabled"]:
                    raise ValueError("이 PC는 다른 Main에 연결되어 있습니다. 연결을 끊은 뒤 요청하세요.")
                peers = value.get("easy_peers", {})
                remembered = peers.get(device)
                if not peers and not remembered and value["switch_delay"] == 250:
                    value["switch_delay"] = 0
                if any(peer != device and record["pin"] == pin for peer, record in peers.items()):
                    raise ValueError("같은 인증서가 다른 PC에 이미 등록되어 있습니다.")
                if remembered and remembered["pin"] != pin:
                    raise ValueError("등록한 PC의 인증서가 달라졌습니다. 연결을 해제하고 다시 등록하세요.")
                if not remembered:
                    if len(peers) >= 16:
                        raise ValueError("연결 가능한 PC 수를 초과했습니다.")
                    if not await self._ask({"device": device, "name": name, "ip": address, "code": confirmation(proof)}, reader):
                        raise ValueError("Main에서 연결 요청을 거절했거나 승인 시간이 지났습니다.")
                    used = {item["name"].casefold() for item in value["screens"]}
                    # Reuse a manually configured screen only when its pin was
                    # already trusted. Otherwise avoid a same-name takeover.
                    if name.casefold() == value["name"].casefold() or name.casefold() in used and pin not in value["trusted_clients"]:
                        name = name[:54] + "-" + device[:8]
                    else:
                        name = next((item["name"] for item in value["screens"] if item["name"].casefold() == name.casefold()), name)
                    value["screens"] = place_screen(value["screens"], name)
                    peers[device] = {"name": name, "pin": pin, "ip": address}
                else:
                    peers[device]["ip"] = address
                value.update(mode="server", enabled=bool(self.config.mouse_enabled), easy_peers=peers)
                value["trusted_clients"] = list(dict.fromkeys(value["trusted_clients"] + [pin]))
                value["easy_revision"] = value.get("easy_revision", 0) + 1
                clipboard_peers = copy.deepcopy(self.config.trusted_peers)
                clipboard_peer = clipboard_peers.get(device) if self.config.role == "main" else None
                shared = unprotect(clipboard_peer["secret"]) if clipboard_peer else secrets.token_bytes(32)
                clipboard_peers[device] = {"name": name, "secret": protect(shared)}
                await self._apply(value, show=not remembered, clipboard={"role": "main", "peer_id": "", "peer_pin": "", "peer_ip": "", "trusted_peers": clipboard_peers, "direction": "both"})
                if device in self.clients:
                    self.clients[device].close()
                self.clients[device] = writer
                await write_frame(writer, {"type": "accepted", "name": peers[device]["name"], **self._snapshot(),
                    "clipboard": {"device": self.config.device_id, "pin": fingerprint(self.config.cert_pem), "port": self.config.port,
                                  "secret": base64.b64encode(shared).decode("ascii")}})
                await self._broadcast()
            self.pending -= 1
            counted = False
            self.notify("input_setup_status", "PC 승인 완료 · 화면 배치 공유 중")
            while True:
                message = await read_frame(reader, 16384, timeout=35)
                if message.get("type") == "ping" and set(message) == {"type"}:
                    await write_frame(writer, {"type": "pong"})
                elif message.get("type") == "layout" and set(message) == {"type", "revision", "screens"}:
                    await self._layout(message["screens"], message["revision"])
                elif message == {"type": "leave"}:
                    await self._remove_peer(device)
                    return
                else:
                    raise ValueError("Unsupported setup operation")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            try:
                await write_frame(writer, {"type": "error", "message": str(error) if isinstance(error, ValueError) else "연결 인증 또는 설정에 실패했습니다."})
            except Exception:
                pass
        finally:
            if counted:
                self.pending -= 1
            if device and self.clients.get(device) is writer:
                del self.clients[device]
                self.notify("input_setup_devices", list(self.clients))
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _snapshot(self):
        value = settings(self.config)
        return {"revision": value.get("easy_revision", 0), "server": self.config.device_id,
                "server_name": value["name"], "port": value["port"], "screens": value["screens"], "enabled": value["enabled"]}

    async def _broadcast(self):
        snapshot = {"type": "layout_state", **self._snapshot()}
        for writer in list(self.clients.values()):
            try:
                await write_frame(writer, snapshot)
            except (OSError, ConnectionError):
                writer.close()
        self.notify("input_setup_devices", list(self.clients))

    async def _layout(self, screens, revision):
        async with self.lock:
            value = settings(self.config)
            if type(revision) is not int or revision != value.get("easy_revision", 0):
                await self._broadcast()
                self.notify("input_setup_status", "다른 PC에서 배치를 변경해 최신 배치를 표시했습니다. 다시 옮겨주세요.")
                return
            value = layout_settings(value, screens)
            value["easy_revision"] = revision + 1
            await self._apply(value)
            await self._broadcast()

    async def _client_state(self, message, address, port, pin, assigned=None):
        value = settings(self.config)
        if assigned is not None and not value.get("easy_controller") and value["switch_delay"] == 250:
            value["switch_delay"] = 0
        if message.get("server") != value.get("easy_controller", message.get("server")):
            raise ValueError("다른 Main의 화면 배치입니다.")
        if type(message.get("revision")) is not int or not 0 <= message["revision"] < 2**63:
            raise ValueError("Invalid layout revision")
        name = computer_name(assigned or value["name"])
        if not isinstance(message.get("screens"), list) or name not in [item.get("name") for item in message["screens"] if isinstance(item, dict)]:
            raise ValueError("화면 배치에서 이 PC를 찾을 수 없습니다.")
        if type(message.get("enabled")) is not bool:
            raise ValueError("Invalid input state")
        value.update(enabled=message["enabled"] and bool(self.config.mouse_enabled), mode="client", name=name, server_ip=address, port=message["port"],
                     screens=copy.deepcopy(message["screens"]), trusted_servers=[pin],
                     easy_controller=valid_id(message["server"]), easy_setup_port=port, easy_revision=message["revision"])
        # Validate all screen options and topology before touching the native core.
        validate({**value, "mode": "server", "name": computer_name(message["server_name"])})
        clipboard = None
        if assigned is not None:
            grant = message.get("clipboard")
            if not isinstance(grant, dict) or set(grant) != {"device", "pin", "port", "secret"} or grant["device"] != value["easy_controller"]:
                raise ValueError("Invalid clipboard enrollment")
            import re
            secret = base64.b64decode(grant["secret"], validate=True)
            if len(secret) != 32 or not isinstance(grant["pin"], str) or not re.fullmatch(r"[0-9a-f]{64}", grant["pin"]) or type(grant["port"]) is not int or not 1024 <= grant["port"] <= 65535:
                raise ValueError("Invalid clipboard credentials")
            clipboard = {"role": "server", "peer_id": grant["device"], "peer_pin": grant["pin"], "peer_ip": address,
                         "port": grant["port"], "protected_secret": protect(secret), "trusted_peers": {}, "direction": "both"}
        await self._apply(value, show=assigned is not None, clipboard=clipboard)

    async def _connect(self, address, port):
        delay = 1
        while not self.stop_event.is_set():
            writer = heartbeat = None
            try:
                self.notify("input_setup_status", "Main 연결 중…")
                reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port, ssl=client_context(),
                    server_hostname=None, ssl_handshake_timeout=5, ssl_shutdown_timeout=1), 8)
                pin = hashlib.sha256(writer.get_extra_info("ssl_object").getpeercert(binary_form=True)).hexdigest()
                value = settings(self.config)
                if (value.get("easy_controller") or value["mode"] == "client" and value["server_ip"] == address and value["trusted_servers"]) and pin not in value["trusted_servers"]:
                    raise ValueError("Main 인증서가 달라졌습니다. 기존 연결을 해제한 뒤 확인하세요.")
                challenge = await read_frame(reader, 4096, timeout=5)
                if set(challenge) != {"type", "protocol", "device", "nonce"} or challenge["type"] != "challenge" or challenge["protocol"] != PROTOCOL:
                    raise ValueError("상대 PC도 새 ClipBridge 버전으로 업데이트하세요.")
                if valid_id(challenge["device"]) == self.config.device_id:
                    raise ValueError("이 PC 자신의 IP입니다. Main PC IP를 입력하세요.")
                if value.get("easy_controller") and challenge["device"] != value["easy_controller"]:
                    raise ValueError("등록된 Main PC와 다릅니다.")
                nonce = secrets.token_hex(32)
                proof = transcript(challenge, self.config.device_id, value["name"], nonce, pin, self.pin)
                await write_frame(writer, {"type": "join", "device": self.config.device_id, "name": value["name"], "nonce": nonce,
                    "certificate": self.cert_pem, "signature": base64.b64encode(signature(self.key, proof)).decode("ascii")})
                self.notify("input_setup_status", "Main에서 승인을 눌러주세요 · 확인 번호 " + confirmation(proof))
                response = await read_frame(reader, 16384, timeout=125)
                if response.get("type") != "accepted":
                    raise ValueError(response.get("message", "Main에서 연결을 승인하지 않았습니다."))
                if response.get("server") != challenge["device"]:
                    raise ValueError("Wrong server")
                await self._client_state(response, address, port, pin, computer_name(response["name"]))
                self.client_writer, delay = writer, 1
                self.notify("input_setup_status", "PC 승인 완료 · 화면 배치 공유 중")
                async def keepalive():
                    while True:
                        await asyncio.sleep(10)
                        await write_frame(writer, {"type": "ping"})
                heartbeat = asyncio.create_task(keepalive())
                while True:
                    message = await read_frame(reader, 16384, timeout=35)
                    if message.get("type") == "layout_state":
                        await self._client_state(message, address, port, pin)
                    elif message.get("type") == "revoked":
                        await self._clear_controller()
                        self.notify("input_setup_status", "Main에서 연결을 해제했습니다. 다시 연결하려면 요청을 보내세요.")
                        return
                    elif message.get("type") != "pong":
                        raise ValueError(message.get("message", "Main과 연결이 끊겼습니다."))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                text = str(error) if isinstance(error, ValueError) else "Main에 연결되지 않습니다. IP와 사설 네트워크 방화벽을 확인하세요."
                self.notify("input_setup_status", text)
                if not settings(self.config).get("easy_controller"):
                    return  # A denied first request must not prompt the host again.
            finally:
                if heartbeat:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
                self.client_writer = None
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
            try:
                await asyncio.wait_for(self.stop_event.wait(), delay)
            except TimeoutError:
                delay = min(delay * 2, 10)

    def connect_to(self, address, port=SETUP_PORT):
        address = private_address(address)
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Invalid setup port")
        async def connect():
            value = settings(self.config)
            if value.get("easy_peers"):
                raise ValueError("이 PC는 이미 Main으로 다른 화면을 연결했습니다.")
            if value.get("easy_controller") and address != value["server_ip"]:
                raise ValueError("기존 Main 연결을 끊은 뒤 다른 IP를 입력하세요.")
            if self.client_task:
                self.client_task.cancel()
                await asyncio.gather(self.client_task, return_exceptions=True)
            self.client_task = asyncio.create_task(self._connect(address, port))
        return self._submit(connect())

    def change_layout(self, screens, revision):
        async def change():
            value = settings(self.config)
            layout_settings(value, screens)
            if value.get("easy_controller"):
                if not self.client_writer:
                    raise ValueError("Main 연결을 기다린 뒤 배치를 변경하세요.")
                await write_frame(self.client_writer, {"type": "layout", "revision": revision, "screens": screens})
            else:
                await self._layout(screens, revision)
        return self._submit(change())

    def publish(self):
        return self._submit(self._broadcast())

    async def _clear_controller(self):
        value = settings(self.config)
        for key in ("easy_controller", "easy_setup_port"):
            value.pop(key, None)
        value.update(enabled=False, mode="server", trusted_servers=[], easy_revision=0,
                     screens=[{"name": value["name"], "x": 1, "y": 1}])
        await self._apply(value, clipboard={"role": "main", "peer_id": "", "peer_pin": "", "peer_ip": "", "trusted_peers": {}, "protected_secret": protect(secrets.token_bytes(32))})

    async def _remove_peer(self, device):
        async with self.lock:
            value = settings(self.config)
            peers = value.get("easy_peers", {})
            record = peers.pop(device, None)
            if not record:
                return
            value["easy_peers"] = peers
            value["trusted_clients"] = [pin for pin in value["trusted_clients"] if pin != record["pin"]]
            value["screens"] = [item for item in value["screens"] if item["name"] != record["name"]]
            try:
                validate(value)
            except ValueError:
                root = next(item for item in value["screens"] if item["name"] == value["name"])
                arranged = [root]
                for item in value["screens"]:
                    if item["name"] != root["name"]:
                        arranged = place_screen(arranged, item["name"])
                value["screens"] = arranged
            value["enabled"] = bool(value["trusted_clients"])
            value["easy_revision"] = value.get("easy_revision", 0) + 1
            clipboard_peers = copy.deepcopy(self.config.trusted_peers)
            clipboard_peers.pop(device, None)
            await self._apply(value, clipboard={"trusted_peers": clipboard_peers})
            writer = self.clients.pop(device, None)
            if writer:
                try:
                    await write_frame(writer, {"type": "revoked"})
                finally:
                    writer.close()
            await self._broadcast()

    def disconnect(self, name):
        async def disconnect():
            value = settings(self.config)
            if value.get("easy_controller"):
                if self.client_writer:
                    await write_frame(self.client_writer, {"type": "leave"})
                if self.client_task:
                    self.client_task.cancel()
                    await asyncio.gather(self.client_task, return_exceptions=True)
                await self._clear_controller()
            else:
                device = next((device for device, record in value.get("easy_peers", {}).items() if record["name"] == name), None)
                if not device:
                    raise ValueError("연결을 해제할 상대 PC 화면을 선택하세요.")
                await self._remove_peer(device)
            self.notify("input_setup_status", "연결을 해제했습니다.")
        return self._submit(disconnect())

    def _submit(self, coroutine):
        if not self.ready.is_set() or self.stopped.is_set() or self.stop_requested.is_set():
            coroutine.close()
            raise ValueError("연결 기능을 준비 중입니다. 잠시 후 다시 시도하세요.")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def stop(self):
        self.stop_requested.set()
        if self.loop and not self.stopped.is_set():
            def stop():
                self.stop_event.set()
                for task in asyncio.all_tasks(self.loop):
                    task.cancel()
            try:
                self.loop.call_soon_threadsafe(stop)
            except RuntimeError:
                pass
        if self.ident:
            self.join(timeout=5)
