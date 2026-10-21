from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import hashlib
import hmac
import json
import secrets
import socket
import struct
import threading
import time
import uuid

from .files import ReceiveTransfer, TransferStore, scan_sources, validate_manifest
from .images import normalize
from .model import CHUNK, MAX_FRAME, Ledger, Snapshot, Stamp, canonical, private_address, valid_id
from .security import client_context, nonce, proof, protect, server_context, unprotect, valid_nonce
from .clipboard import sequence
from .config import CONFIG_LOCK
from .streaming import ClipboardAssembly


async def read_frame(reader, limit=MAX_FRAME, timeout=45):
    async with asyncio.timeout(timeout):
        size = struct.unpack("!I", await reader.readexactly(4))[0]
        if not 0 < size <= limit:
            raise ValueError("frame size limit")
        value = json.loads(await reader.readexactly(size))
        if not isinstance(value, dict):
            raise ValueError("invalid message")
        return value


async def write_frame(writer, value):
    data = canonical(value)
    if len(data) > MAX_FRAME:
        raise ValueError("frame size limit")
    writer.write(struct.pack("!I", len(data)) + data)
    async with asyncio.timeout(20):
        await writer.drain()


class NetworkEngine(threading.Thread):
    def __init__(self, config, ledger: Ledger, store: TransferStore, apply, notify, approve, paired, persist=None):
        super().__init__(name="ClipBridge-network", daemon=True)
        self.config, self.ledger, self.store = config, ledger, store
        self.apply, self.notify, self.approve, self.paired = apply, notify, approve, paired
        self.loop = None
        self.sessions: dict[str, Session] = {}
        self.persist = persist or (lambda config: None)
        self.pending = 0
        self.peer_caps = {}
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.stop_requested = threading.Event()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event = asyncio.Event()
        self.pair_lock = asyncio.Lock()
        self.ready.set()
        try:
            self.loop.run_until_complete(self._run())
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self.notify("status", "연결 시작 실패 (" + type(error).__name__ + ") · IP/포트 설정을 확인하세요")
        finally:
            tasks = asyncio.all_tasks(self.loop)
            for task in tasks:
                task.cancel()
            if tasks:
                self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
            self.loop.close()
            self.notify("connected", 0)
            self.notify("devices", [])
            self.stopped.set()

    async def _run(self):
        if self.stop_requested.is_set():
            return
        if self.config.migrate_trust():
            self.persist(self.config)
        self.config.validate()
        if self.config.role == "main":
            context = await asyncio.to_thread(server_context, self.config.cert_pem, self.config.protected_key)
            server = await asyncio.start_server(self._accept, self.config.bind_ip, self.config.port, ssl=context,
                                                ssl_handshake_timeout=8, ssl_shutdown_timeout=2, backlog=16)
            self.notify("status", "허브 연결 대기 중 · 새 컴퓨터마다 연결 코드를 복사하세요")
            async with server:
                await self.stop_event.wait()
        else:
            delay = 1
            while not self.stop_event.is_set():
                writer = None
                try:
                    async with asyncio.timeout(10):
                        reader, writer = await asyncio.open_connection(self.config.peer_ip, self.config.port, ssl=client_context(), server_hostname=None,
                                                                       ssl_handshake_timeout=8, ssl_shutdown_timeout=2)
                    cert = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
                    if not hmac.compare_digest(hashlib.sha256(cert).hexdigest(), self.config.peer_pin):
                        raise ValueError("certificate pin mismatch")
                    peer, relay = await self._client_auth(reader, writer)
                    delay = 1
                    await self._session(reader, writer, peer, relay)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.notify("status", "연결 끊김 · 자동 재연결 대기 (" + type(error).__name__ + ")")
                finally:
                    if writer:
                        writer.close()
                        try:
                            await writer.wait_closed()
                        except Exception:
                            pass
                try:
                    await asyncio.wait_for(self.stop_event.wait(), delay)
                except TimeoutError:
                    delay = min(delay * 2, 15)

    async def _accept(self, reader, writer):
        counted = False
        try:
            address = writer.get_extra_info("peername")[0]
            private_address(address)
            if len(self.sessions) >= 16 or self.pending >= 8:
                return
            self.pending += 1
            counted = True
            async with asyncio.timeout(130):
                peer, relay = await self._server_auth(reader, writer)
            self.pending -= 1
            counted = False
            if peer in self.sessions or self.stop_event.is_set():
                return
            await self._session(reader, writer, peer, relay)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.notify("status", "연결이 거부되었거나 끊겼습니다 (" + type(error).__name__ + ")")
        finally:
            if counted:
                self.pending -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def ask(self, kind, info, valid=None):
        future = concurrent.futures.Future()
        self.approve(kind, info, future)
        try:
            wrapped = asyncio.wrap_future(future)
            async with asyncio.timeout(120):
                while True:
                    if valid is not None and not valid():
                        return False
                    try:
                        return bool(await asyncio.wait_for(asyncio.shield(wrapped), .25))
                    except TimeoutError:
                        pass
        except TimeoutError:
            return False
        finally:
            if not future.done():
                future.cancel()

    async def _server_auth(self, reader, writer):
        server_id, server_nonce = self.config.device_id, nonce()
        await write_frame(writer, {"type": "challenge", "version": 1, "relay": 2, "device": server_id, "nonce": server_nonce})
        request = await read_frame(reader, 8192, timeout=10)
        client_id, client_nonce = valid_id(request.get("device")), valid_nonce(request.get("nonce"))
        if client_id == server_id or client_id in self.sessions:
            raise ValueError("duplicate device")
        def verify(secret):
            expected = proof(secret, "client", server_id, client_id, server_nonce, client_nonce)
            if request.get("type") != "auth" or not isinstance(request.get("proof"), str) or not hmac.compare_digest(expected, request["proof"]):
                raise ValueError("authentication failed")
        record = self.config.trusted_peers.get(client_id)
        if record:
            secret = unprotect(record["secret"])
            verify(secret)
        else:
            # One invitation pairs one device. Existing devices never know the next key.
            async with self.pair_lock:
                secret = self.config.secret
                verify(secret)
                if len(self.config.trusted_peers) >= 16 or client_id in self.config.trusted_peers:
                    raise ValueError("device limit or duplicate pairing")
                name = request.get("name", "컴퓨터")
                if not isinstance(name, str) or not 1 <= len(name) <= 64 or any(ord(c) < 32 for c in name):
                    raise ValueError("invalid device name")
                if not await self.ask("pair", {"device": client_id, "ip": writer.get_extra_info("peername")[0], "name": name}):
                    raise ValueError("pairing denied")
                with CONFIG_LOCK:
                    old_secret = self.config.protected_secret
                    self.config.trusted_peers[client_id] = {"secret": protect(secret), "name": name}
                    self.config.protected_secret = protect(secrets.token_bytes(32))
                    try:
                        self.persist(self.config)
                    except Exception:
                        del self.config.trusted_peers[client_id]
                        self.config.protected_secret = old_secret
                        raise
                self.paired(client_id)
        self.ledger.observe(request.get("clock"))
        self.peer_caps[client_id] = self.capabilities(request)
        relay = 2 if request.get("relay") == 2 else 1
        await write_frame(writer, {"type": "ready", "relay": relay, "clip_stream": 1, "clip_limit": self.config.clip_limit, "file_limit": self.config.file_limit, "clock": self.ledger.clock, "proof": proof(secret, "server", server_id, client_id, server_nonce, client_nonce)})
        return client_id, relay

    async def _client_auth(self, reader, writer):
        challenge = await read_frame(reader, 8192, timeout=10)
        server_id, server_nonce = valid_id(challenge.get("device")), valid_nonce(challenge.get("nonce"))
        if challenge.get("type") != "challenge" or challenge.get("version") != 1 or server_id != self.config.peer_id:
            raise ValueError("wrong server")
        client_id, client_nonce = self.config.device_id, nonce()
        await write_frame(writer, {"type": "auth", "relay": 2, "clip_stream": 1, "clip_limit": self.config.clip_limit, "file_limit": self.config.file_limit, "name": socket.gethostname()[:64] or "컴퓨터", "device": client_id, "nonce": client_nonce, "clock": self.ledger.clock,
                                   "proof": proof(self.config.secret, "client", server_id, client_id, server_nonce, client_nonce)})
        ready = await read_frame(reader, 8192, timeout=125)
        expected = proof(self.config.secret, "server", server_id, client_id, server_nonce, client_nonce)
        if ready.get("type") != "ready" or not isinstance(ready.get("proof"), str) or not hmac.compare_digest(expected, ready["proof"]):
            raise ValueError("server authentication failed")
        self.ledger.observe(ready.get("clock"))
        self.peer_caps[server_id] = self.capabilities(ready)
        return server_id, 2 if ready.get("relay") == 2 else 1

    @staticmethod
    def capabilities(message):
        from .model import MAX_CLIP, MAX_TOTAL
        clip, files = message.get("clip_limit", 96 * 1024**2), message.get("file_limit", 1024**3)
        if type(clip) is not int or type(files) is not int or not 0 < clip <= MAX_CLIP or not 0 < files <= MAX_TOTAL:
            raise ValueError("invalid peer limits")
        return {"stream": message.get("clip_stream") == 1, "clip": clip, "files": files}

    async def _session(self, reader, writer, peer, relay):
        session = Session(self, reader, writer, peer, relay)
        self.sessions[peer] = session
        self.connection_state()
        self.notify("status", "연결됨 · 새 복사부터 자동 동기화")
        try:
            await session.run()
        finally:
            self.sessions.pop(peer, None)
            self.connection_state()

    def connection_state(self):
        self.notify("connected", len(self.sessions))
        self.notify("devices", list(self.sessions))

    def broadcast(self, snapshot, exclude=None):
        if not self.config.can_send() or not self.ledger.current(snapshot.stamp):
            return
        for peer, session in list(self.sessions.items()):
            if peer != exclude:
                # Old clients accept only snapshots authored by their direct peer.
                if session.relay < 2 and snapshot.stamp.device != self.config.device_id:
                    self.notify("status", "여러 대 공유를 위해 모든 컴퓨터를 v1.2 이상으로 업데이트하세요.")
                    continue
                session.submit(snapshot)

    def submit(self, snapshot: Snapshot):
        if not self.loop or self.stopped.is_set():
            return
        def dispatch():
            if self.sessions and self.config.can_send():
                self.broadcast(snapshot)
            else:
                self.notify("status", "연결되지 않아 이번 복사는 전송되지 않았습니다.")
        self.loop.call_soon_threadsafe(dispatch)

    def stop(self):
        self.stop_requested.set()
        if self.loop and not self.stopped.is_set():
            def finish():
                self.stop_event.set()
                for task in asyncio.all_tasks(self.loop):
                    task.cancel()
            try:
                self.loop.call_soon_threadsafe(finish)
            except RuntimeError:
                pass
        self.join(timeout=5)


class Session:
    def __init__(self, engine, reader, writer, peer, relay=2):
        self.engine, self.reader, self.writer, self.peer = engine, reader, writer, peer
        self.config, self.ledger = engine.config, engine.ledger
        self.relay = relay
        self.caps = engine.peer_caps.get(peer, {"stream": False, "clip": 96 * 1024**2, "files": 1024**3})
        self.write_lock = asyncio.Lock()
        self.outgoing = None
        self.tasks = set()
        self.waiters = {}
        self.receiving = None
        self.in_stamp = None
        self.in_id = ""
        self.last_digest = ""
        self.closed = False
        self.clipboard_receiving = None
        self.file_formats_receiving = None

    async def send(self, value):
        async with self.write_lock:
            await write_frame(self.writer, value)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def done(result):
            self.tasks.discard(result)
            if not result.cancelled() and result.exception():
                self.engine.notify("status", "전송 처리 실패 (" + type(result.exception()).__name__ + ")")
        task.add_done_callback(done)
        return task

    async def run(self):
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            while True:
                message = await read_frame(self.reader)
                await self.receive(message)
        finally:
            self.closed = True
            self.clipboard_receiving = None
            self.file_formats_receiving = None
            heartbeat.cancel()
            if self.outgoing:
                self.outgoing.cancel()
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(heartbeat, *self.tasks, return_exceptions=True)
            if self.receiving:
                self.receiving.remove()
                self.receiving = None
            for waiter in self.waiters.values():
                if not waiter.done():
                    waiter.cancel()
            self.writer.close()

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(10)
            await self.send({"type": "ping"})
            if self.receiving and (not self.ledger.current(self.in_stamp) or asyncio.get_running_loop().time() - self.receiving.updated > 120):
                self.receiving.remove()
                self.receiving = None
                self.file_formats_receiving = None
            if self.clipboard_receiving and (not self.ledger.current(self.clipboard_receiving.stamp) or time.monotonic() - self.clipboard_receiving.updated > 120):
                self.clipboard_receiving = None

    def submit(self, snapshot):
        if not self.ledger.current(snapshot.stamp):
            return
        if self.outgoing:
            self.outgoing.cancel()
        lease = self.engine.store.pin(snapshot.paths)
        self.outgoing = self.spawn(self._outbound(snapshot))
        self.outgoing.add_done_callback(lambda task: self.engine.store.release(lease))

    async def _outbound(self, snapshot):
        transfer_id = str(uuid.uuid4())
        file_offer = False
        clipboard_offer = False
        try:
            if sum(map(len, snapshot.formats.values())) > self.caps["clip"]:
                self.engine.notify("status", "상대 컴퓨터의 클립보드 용량 제한을 높인 뒤 다시 복사하세요.")
                return
            if snapshot.paths:
                self.engine.notify("status", "파일 확인 중 · 새 복사 시 이전 전송 취소")
                cancelled = threading.Event()
                scan = asyncio.create_task(asyncio.to_thread(scan_sources, snapshot.paths, self.config.file_limit,
                                           lambda: cancelled.is_set() or self.closed or not self.ledger.current(snapshot.stamp)))
                try:
                    manifest, sources = await asyncio.shield(scan)
                except asyncio.CancelledError:
                    cancelled.set()
                    await asyncio.gather(scan, return_exceptions=True)
                    raise
                if not self.ledger.current(snapshot.stamp):
                    return
                if manifest["total"] > self.caps["files"]:
                    self.engine.notify("status", "상대 컴퓨터의 파일 용량 제한을 높인 뒤 다시 복사하세요.")
                    return
                waiter = asyncio.get_running_loop().create_future()
                self.waiters[transfer_id] = waiter
                file_offer = True
                stream_formats = self.caps["stream"] and sum(map(len, snapshot.formats.values())) > 1024**2
                extra = {"sizes": {name: len(data) for name, data in snapshot.formats.items()}, "digest": await asyncio.to_thread(Snapshot(snapshot.formats).digest)} if stream_formats else {}
                await self.send({"type": "file_offer", "id": transfer_id, "stamp": snapshot.stamp.wire(), "manifest": manifest,
                                 "formats": {} if stream_formats else await asyncio.to_thread(snapshot.wire), **extra})
                accepted = await asyncio.wait_for(waiter, 125)
                if not accepted:
                    self.engine.notify("status", "상대 PC에서 파일 수신을 허용하지 않았습니다.")
                    return
                if stream_formats:
                    for name, data in snapshot.formats.items():
                        for offset in range(0, len(data), CHUNK):
                            if not self.ledger.current(snapshot.stamp) or not self.config.can_send():
                                raise InterruptedError("superseded")
                            await self.send({"type": "file_format_chunk", "id": transfer_id, "format": name, "offset": offset,
                                "data": base64.b64encode(data[offset:offset + CHUNK]).decode("ascii")})
                count = 0
                for entry in manifest["entries"]:
                    if entry["kind"] != "file":
                        continue
                    source = sources[entry["path"]]
                    # Scan rejected junctions; verify again immediately before reading.
                    from .files import assert_local_regular
                    await asyncio.to_thread(assert_local_regular, source)
                    stream = await asyncio.to_thread(source.open, "rb")
                    try:
                        offset, digest = 0, hashlib.sha256()
                        while chunk := await asyncio.to_thread(stream.read, CHUNK):
                            if not self.ledger.current(snapshot.stamp) or not self.config.can_send():
                                raise InterruptedError("superseded")
                            digest.update(chunk)
                            await self.send({"type": "file_chunk", "id": transfer_id, "path": entry["path"], "offset": offset, "data": base64.b64encode(chunk).decode("ascii")})
                            offset += len(chunk)
                            count += len(chunk)
                            if count % (4 * 1024 * 1024) < CHUNK:
                                self.engine.notify("status", f"파일 전송 중 {count // 1024**2}/{manifest['total'] // 1024**2} MiB")
                        if offset != entry["size"] or digest.hexdigest() != entry["sha256"]:
                            raise ValueError("source file changed")
                    finally:
                        await asyncio.to_thread(stream.close)
                await self.send({"type": "file_end", "id": transfer_id})
            else:
                if self.caps["stream"] and sum(map(len, snapshot.formats.values())) > 1024**2:
                    clipboard_offer = True
                    waiter = asyncio.get_running_loop().create_future()
                    self.waiters[transfer_id] = waiter
                    digest = await asyncio.to_thread(snapshot.digest)
                    await self.send({"type": "clip_offer", "id": transfer_id, "stamp": snapshot.stamp.wire(), "sizes": {name: len(data) for name, data in snapshot.formats.items()}, "digest": digest})
                    if not await asyncio.wait_for(waiter, 15):
                        self.engine.notify("status", "상대 컴퓨터가 클립보드 항목을 받지 않았습니다.")
                        return
                    for name, data in snapshot.formats.items():
                        for offset in range(0, len(data), CHUNK):
                            if not self.ledger.current(snapshot.stamp) or not self.config.can_send():
                                raise InterruptedError("superseded")
                            await self.send({"type": "clip_chunk", "id": transfer_id, "format": name, "offset": offset, "data": base64.b64encode(data[offset:offset + CHUNK]).decode("ascii")})
                    await self.send({"type": "clip_end", "id": transfer_id})
                    return
                wire = await asyncio.to_thread(snapshot.wire)
                if self.ledger.current(snapshot.stamp):
                    await self.send({"type": "clipboard", "id": transfer_id, "stamp": snapshot.stamp.wire(), "formats": wire, "digest": snapshot.digest()})
        except (asyncio.CancelledError, InterruptedError):
            if file_offer and not self.closed and not self.engine.stop_requested.is_set():
                await self.send({"type": "file_abort", "id": transfer_id})
            elif clipboard_offer and not self.closed and not self.engine.stop_requested.is_set():
                await self.send({"type": "clip_abort", "id": transfer_id})
        finally:
            self.waiters.pop(transfer_id, None)

    async def _apply(self, snapshot, event_id, transfer=None):
        future = concurrent.futures.Future()
        def completed(ok):
            if not future.done():
                future.set_result(ok)
        self.engine.apply(snapshot, completed)
        try:
            ok = await asyncio.wait_for(asyncio.wrap_future(future), 10)
        except TimeoutError:
            ok = False
        except asyncio.CancelledError:
            if transfer:
                transfer.remove()
            raise
        if transfer:
            if ok:
                self.engine.store.retain(transfer)
            else:
                transfer.remove()
        if ok and self.config.role == "main":
            self.engine.broadcast(snapshot, exclude=self.peer)
        if not self.closed:
            await self.send({"type": "ack", "id": event_id, "ok": ok, "formats": list(snapshot.formats) if not transfer else ["파일"]})

    def _stamp(self, message):
        valid_id(message.get("id"))
        stamp = Stamp.parse(message.get("stamp"))
        if stamp.device != self.peer and (self.config.role == "main" or self.relay < 2):
            raise ValueError("spoofed clipboard origin")
        return stamp

    async def receive(self, message):
        kind = message.get("type")
        if kind == "ping":
            await self.send({"type": "pong"})
        elif kind == "pong":
            pass
        elif kind == "ack":
            if message.get("ok") is True:
                self.engine.notify("sent", message.get("formats", []))
            else:
                self.engine.notify("status", "상대 PC의 새 복사/일시 중지로 이전 항목이 적용되지 않았습니다.")
        elif kind == "clipboard":
            stamp = self._stamp(message)
            if not self.config.can_receive():
                await self.send({"type": "ack", "id": message["id"], "ok": False})
                return
            expected_sequence = sequence()
            snapshot = await asyncio.to_thread(Snapshot.decode, message.get("formats"), self.config.clip_limit)
            digest = snapshot.digest()
            if not isinstance(message.get("digest"), str) or not hmac.compare_digest(digest, message["digest"]):
                raise ValueError("clipboard integrity failure")
            if not self.ledger.claim(stamp):
                await self.send({"type": "ack", "id": message["id"], "ok": False})
                return
            snapshot = snapshot.filtered(self.config.text, self.config.images)
            if not snapshot.formats:
                await self.send({"type": "ack", "id": message["id"], "ok": False})
                return
            snapshot.formats = await asyncio.to_thread(normalize, snapshot.formats, self.config.clip_limit, incoming=True)
            snapshot.stamp = stamp
            snapshot.sequence = expected_sequence
            self.spawn(self._apply(snapshot, message["id"]))
        elif kind == "clip_offer":
            stamp = self._stamp(message)
            assembly = ClipboardAssembly(message["id"], stamp, sequence(), message.get("sizes"), message.get("digest"), self.config.clip_limit)
            accepted = self.config.can_receive() and self.ledger.claim(stamp)
            if accepted:
                self.clipboard_receiving = assembly
            await self.send({"type": "clip_accept", "id": message["id"], "ok": bool(accepted)})
        elif kind == "clip_accept":
            waiter = self.waiters.get(message.get("id"))
            if waiter and not waiter.done():
                waiter.set_result(message.get("ok") is True)
        elif kind == "clip_chunk":
            assembly = self.clipboard_receiving
            if assembly and assembly.id == message.get("id"):
                if not self.ledger.current(assembly.stamp) or not self.config.can_receive():
                    self.clipboard_receiving = None
                    return
                encoded = message.get("data")
                if not isinstance(encoded, str) or len(encoded) > CHUNK * 4 // 3 + 4:
                    raise ValueError("clipboard chunk size")
                assembly.chunk(message.get("format"), message.get("offset"), base64.b64decode(encoded, validate=True))
        elif kind == "clip_end":
            assembly = self.clipboard_receiving
            if assembly and assembly.id == message.get("id"):
                self.clipboard_receiving = None
                snapshot = await asyncio.to_thread(assembly.finish)
                snapshot = snapshot.filtered(self.config.text, self.config.images)
                if snapshot.formats and self.config.can_receive() and self.ledger.current(snapshot.stamp):
                    snapshot.formats = await asyncio.to_thread(normalize, snapshot.formats, self.config.clip_limit, incoming=True)
                    self.spawn(self._apply(snapshot, message["id"]))
                else:
                    await self.send({"type": "ack", "id": message["id"], "ok": False})
        elif kind == "clip_abort":
            if self.clipboard_receiving and self.clipboard_receiving.id == message.get("id"):
                self.clipboard_receiving = None
        elif kind == "file_offer":
            stamp = self._stamp(message)
            manifest = validate_manifest(message.get("manifest"), self.config.file_limit)
            if not self.config.can_receive() or not self.config.files or self.config.file_policy == "block" or not self.ledger.claim(stamp):
                await self.send({"type": "file_accept", "id": message["id"], "ok": False})
                return
            if self.receiving:
                self.receiving.remove()
                self.receiving = None
            self.in_stamp, self.in_id = stamp, message["id"]
            self.in_sequence = sequence()
            self.in_formats = {}
            self.file_formats_receiving = None
            if "sizes" in message:
                self.file_formats_receiving = ClipboardAssembly(message["id"], stamp, self.in_sequence,
                    message["sizes"], message.get("digest"), self.config.clip_limit)
            if message.get("formats"):
                extra = await asyncio.to_thread(Snapshot.decode, message["formats"], self.config.clip_limit)
                extra = extra.filtered(self.config.text, self.config.images)
                self.in_formats = await asyncio.to_thread(normalize, extra.formats, self.config.clip_limit, incoming=True)
            self.spawn(self._offer(message["id"], stamp, manifest))
        elif kind == "file_accept":
            waiter = self.waiters.get(message.get("id"))
            if waiter and not waiter.done():
                waiter.set_result(message.get("ok") is True)
        elif kind == "file_chunk":
            if self.receiving and message.get("id") == self.in_id:
                if not self.ledger.current(self.in_stamp) or not self.config.can_receive():
                    self.receiving.remove()
                    self.receiving = None
                    return
                encoded = message.get("data")
                if not isinstance(encoded, str) or len(encoded) > CHUNK * 4 // 3 + 4:
                    raise ValueError("chunk size")
                data = base64.b64decode(encoded, validate=True)
                await asyncio.to_thread(self.receiving.chunk, message.get("path"), message.get("offset"), data)
        elif kind == "file_format_chunk":
            assembly = self.file_formats_receiving
            if self.receiving and assembly and message.get("id") == self.in_id:
                if not self.ledger.current(self.in_stamp) or not self.config.can_receive():
                    self.file_formats_receiving = None
                    return
                encoded = message.get("data")
                if not isinstance(encoded, str) or len(encoded) > CHUNK * 4 // 3 + 4:
                    raise ValueError("file format chunk size")
                assembly.chunk(message.get("format"), message.get("offset"), base64.b64decode(encoded, validate=True))
                self.receiving.updated = time.monotonic()
        elif kind == "file_end":
            if self.receiving and message.get("id") == self.in_id:
                transfer, self.receiving = self.receiving, None
                try:
                    paths = await asyncio.to_thread(transfer.finish)
                    if self.file_formats_receiving:
                        assembly, self.file_formats_receiving = self.file_formats_receiving, None
                        extra = await asyncio.to_thread(assembly.finish)
                        extra = extra.filtered(self.config.text, self.config.images)
                        self.in_formats = await asyncio.to_thread(normalize, extra.formats, self.config.clip_limit, incoming=True)
                except BaseException:
                    transfer.remove()
                    raise
                snapshot = Snapshot(self.in_formats, paths, self.in_stamp, self.in_sequence)
                self.spawn(self._apply(snapshot, message["id"], transfer))
        elif kind == "file_abort":
            if message.get("id") == self.in_id:
                self.in_id = ""
                self.file_formats_receiving = None
                if self.receiving:
                    self.receiving.remove()
                    self.receiving = None
        else:
            raise ValueError("unknown protocol message")

    async def _offer(self, event_id, stamp, manifest):
        accepted = self.config.file_policy == "allow" or stamp.device in self.config.file_allow_ids or await self.engine.ask("files", {"device": stamp.device, "count": len(manifest["entries"]), "total": manifest["total"]},
            lambda: self.ledger.current(stamp) and self.in_id == event_id and not self.closed and self.config.can_receive())
        accepted = accepted and self.ledger.current(stamp) and self.in_id == event_id and self.config.can_receive() and self.config.files and self.config.file_policy != "block"
        if accepted:
            create = asyncio.create_task(asyncio.to_thread(ReceiveTransfer, self.engine.store.base, event_id, manifest))
            try:
                transfer = await asyncio.shield(create)
            except asyncio.CancelledError:
                result = await asyncio.gather(create, return_exceptions=True)
                if isinstance(result[0], ReceiveTransfer):
                    result[0].remove()
                raise
            except (ValueError, OSError):
                self.engine.notify("status", "파일 수신 공간이 부족하거나 임시 폴더를 만들 수 없습니다.")
                await self.send({"type": "file_accept", "id": event_id, "ok": False})
                return
            if self.in_id == event_id and self.ledger.current(stamp) and not self.closed:
                self.receiving = transfer
                self.engine.notify("status", "파일 자동 수신 중" if self.config.file_policy == "allow" else "승인한 파일 수신 중")
            else:
                transfer.remove()
                accepted = False
        await self.send({"type": "file_accept", "id": event_id, "ok": bool(accepted)})
