from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import hashlib
import hmac
import ipaddress
import json
import socket
import struct
import threading
import uuid

from .files import ReceiveTransfer, TransferStore, scan_sources, validate_manifest
from .images import normalize
from .model import CHUNK, MAX_FRAME, Ledger, Snapshot, Stamp, canonical, valid_id
from .security import client_context, nonce, proof, server_context, valid_nonce
from .clipboard import sequence


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
    def __init__(self, config, ledger: Ledger, store: TransferStore, apply, notify, approve, paired):
        super().__init__(name="ClipBridge-network", daemon=True)
        self.config, self.ledger, self.store = config, ledger, store
        self.apply, self.notify, self.approve, self.paired = apply, notify, approve, paired
        self.loop = None
        self.session: Session | None = None
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.last_sent_hash = ""

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event = asyncio.Event()
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
            self.notify("connected", False)
            self.stopped.set()

    async def _run(self):
        self.config.validate()
        if self.config.role == "main":
            context = await asyncio.to_thread(server_context, self.config.cert_pem, self.config.protected_key)
            server = await asyncio.start_server(self._accept, self.config.bind_ip, self.config.port, ssl=context,
                                                ssl_handshake_timeout=8, ssl_shutdown_timeout=2, backlog=4)
            self.notify("status", "연결 대기 중 · 지정한 상대 PC만 허용")
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
                    peer = await self._client_auth(reader, writer)
                    delay = 1
                    await self._session(reader, writer, peer)
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
        try:
            address = writer.get_extra_info("peername")[0]
            if ipaddress.ip_address(address) != ipaddress.ip_address(self.config.peer_ip) or self.session:
                return
            async with asyncio.timeout(130):
                peer = await self._server_auth(reader, writer)
            if self.session or self.stop_event.is_set():
                return
            await self._session(reader, writer, peer)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.notify("status", "연결이 거부되었거나 끊겼습니다 (" + type(error).__name__ + ")")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def ask(self, kind, info):
        future = concurrent.futures.Future()
        self.approve(kind, info, future)
        try:
            return bool(await asyncio.wait_for(asyncio.wrap_future(future), 120))
        except TimeoutError:
            return False

    async def _server_auth(self, reader, writer):
        server_id, server_nonce = self.config.device_id, nonce()
        await write_frame(writer, {"type": "challenge", "version": 1, "device": server_id, "nonce": server_nonce})
        request = await read_frame(reader, 8192, timeout=10)
        client_id, client_nonce = valid_id(request.get("device")), valid_nonce(request.get("nonce"))
        expected = proof(self.config.secret, "client", server_id, client_id, server_nonce, client_nonce)
        if request.get("type") != "auth" or not isinstance(request.get("proof"), str) or not hmac.compare_digest(expected, request["proof"]):
            raise ValueError("authentication failed")
        if self.config.peer_id and self.config.peer_id != client_id:
            raise ValueError("unapproved device")
        if not self.config.peer_id:
            if not await self.ask("pair", {"device": client_id, "ip": self.config.peer_ip}):
                raise ValueError("pairing denied")
            self.config.peer_id = client_id
            self.paired(client_id)
        self.ledger.observe(request.get("clock"))
        await write_frame(writer, {"type": "ready", "clock": self.ledger.clock, "proof": proof(self.config.secret, "server", server_id, client_id, server_nonce, client_nonce)})
        return client_id

    async def _client_auth(self, reader, writer):
        challenge = await read_frame(reader, 8192, timeout=10)
        server_id, server_nonce = valid_id(challenge.get("device")), valid_nonce(challenge.get("nonce"))
        if challenge.get("type") != "challenge" or challenge.get("version") != 1 or server_id != self.config.peer_id:
            raise ValueError("wrong server")
        client_id, client_nonce = self.config.device_id, nonce()
        await write_frame(writer, {"type": "auth", "device": client_id, "nonce": client_nonce, "clock": self.ledger.clock,
                                   "proof": proof(self.config.secret, "client", server_id, client_id, server_nonce, client_nonce)})
        ready = await read_frame(reader, 8192, timeout=125)
        expected = proof(self.config.secret, "server", server_id, client_id, server_nonce, client_nonce)
        if ready.get("type") != "ready" or not isinstance(ready.get("proof"), str) or not hmac.compare_digest(expected, ready["proof"]):
            raise ValueError("server authentication failed")
        self.ledger.observe(ready.get("clock"))
        return server_id

    async def _session(self, reader, writer, peer):
        session = Session(self, reader, writer, peer)
        self.session = session
        self.last_sent_hash = ""
        self.notify("connected", True)
        self.notify("status", "연결됨 · 새 복사부터 자동 동기화")
        try:
            await session.run()
        finally:
            self.session = None
            self.notify("connected", False)

    def submit(self, snapshot: Snapshot):
        if not self.loop or self.stopped.is_set():
            return
        def dispatch():
            if self.session and self.config.can_send():
                self.session.submit(snapshot)
            else:
                self.notify("status", "연결되지 않아 이번 복사는 전송되지 않았습니다.")
        self.loop.call_soon_threadsafe(dispatch)

    def stop(self):
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
    def __init__(self, engine, reader, writer, peer):
        self.engine, self.reader, self.writer, self.peer = engine, reader, writer, peer
        self.config, self.ledger = engine.config, engine.ledger
        self.write_lock = asyncio.Lock()
        self.outgoing = None
        self.tasks = set()
        self.waiters = {}
        self.receiving = None
        self.in_stamp = None
        self.in_id = ""
        self.last_digest = ""
        self.closed = False

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

    def submit(self, snapshot):
        if not self.ledger.current(snapshot.stamp):
            return
        if self.outgoing:
            self.outgoing.cancel()
        self.outgoing = self.spawn(self._outbound(snapshot))

    async def _outbound(self, snapshot):
        transfer_id = str(uuid.uuid4())
        file_offer = False
        try:
            if snapshot.paths:
                self.engine.notify("status", "파일 확인 중 · 새 복사 시 이전 전송 취소")
                manifest, sources = await asyncio.to_thread(scan_sources, snapshot.paths, self.config.file_limit,
                                                           lambda: self.closed or not self.ledger.current(snapshot.stamp))
                if not self.ledger.current(snapshot.stamp):
                    return
                waiter = asyncio.get_running_loop().create_future()
                self.waiters[transfer_id] = waiter
                file_offer = True
                await self.send({"type": "file_offer", "id": transfer_id, "stamp": snapshot.stamp.wire(), "manifest": manifest,
                                 "formats": snapshot.wire()})
                accepted = await asyncio.wait_for(waiter, 125)
                if not accepted:
                    self.engine.notify("status", "상대 PC에서 파일 수신을 허용하지 않았습니다.")
                    return
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
                wire = await asyncio.to_thread(snapshot.wire)
                if self.ledger.current(snapshot.stamp):
                    await self.send({"type": "clipboard", "id": transfer_id, "stamp": snapshot.stamp.wire(), "formats": wire, "digest": snapshot.digest()})
        except (asyncio.CancelledError, InterruptedError):
            if file_offer and not self.closed:
                await self.send({"type": "file_abort", "id": transfer_id})
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
        if not self.closed:
            await self.send({"type": "ack", "id": event_id, "ok": ok, "formats": list(snapshot.formats) if not transfer else ["파일"]})

    def _stamp(self, message):
        valid_id(message.get("id"))
        stamp = Stamp.parse(message.get("stamp"))
        if stamp.device != self.peer:
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
        elif kind == "file_end":
            if self.receiving and message.get("id") == self.in_id:
                transfer, self.receiving = self.receiving, None
                try:
                    paths = await asyncio.to_thread(transfer.finish)
                except Exception:
                    transfer.remove()
                    raise
                snapshot = Snapshot(self.in_formats, paths, self.in_stamp, self.in_sequence)
                self.spawn(self._apply(snapshot, message["id"], transfer))
        elif kind == "file_abort":
            if message.get("id") == self.in_id:
                self.in_id = ""
                if self.receiving:
                    self.receiving.remove()
                    self.receiving = None
        else:
            raise ValueError("unknown protocol message")

    async def _offer(self, event_id, stamp, manifest):
        accepted = self.config.file_policy == "allow" or await self.engine.ask("files", {"count": len(manifest["entries"]), "total": manifest["total"]})
        accepted = accepted and self.ledger.current(stamp) and self.in_id == event_id and self.config.can_receive() and self.config.files and self.config.file_policy != "block"
        if accepted:
            transfer = await asyncio.to_thread(ReceiveTransfer, self.engine.store.base, event_id, manifest)
            if self.in_id == event_id and self.ledger.current(stamp) and not self.closed:
                self.receiving = transfer
                self.engine.notify("status", "승인한 파일 수신 중")
            else:
                transfer.remove()
                accepted = False
        await self.send({"type": "file_accept", "id": event_id, "ok": bool(accepted)})
