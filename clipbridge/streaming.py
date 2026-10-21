"""Bounded clipboard chunks: never encode a large clipboard as one JSON frame."""
import hmac
import time

from .model import CHUNK, FORMATS, Snapshot


class ClipboardAssembly:
    def __init__(self, event_id, stamp, sequence, sizes, digest, limit):
        if not isinstance(sizes, dict) or not sizes or len(sizes) > len(FORMATS):
            raise ValueError("invalid clipboard manifest")
        if any(name not in FORMATS or type(size) is not int or size < 0 for name, size in sizes.items()) or sum(sizes.values()) > limit:
            raise ValueError("clipboard size limit")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid clipboard digest")
        self.id, self.stamp, self.sequence, self.sizes, self.digest = event_id, stamp, sequence, sizes, digest
        self.buffers = {name: bytearray() for name in sizes}
        self.updated = time.monotonic()

    def chunk(self, name, offset, data):
        target = self.buffers.get(name)
        if target is None or type(offset) is not int or offset != len(target) or not 0 < len(data) <= CHUNK or offset + len(data) > self.sizes[name]:
            raise ValueError("invalid clipboard chunk")
        target.extend(data)
        self.updated = time.monotonic()

    def finish(self):
        if any(len(self.buffers[name]) != size for name, size in self.sizes.items()):
            raise ValueError("incomplete clipboard")
        formats = {name: bytes(data) for name, data in self.buffers.items()}
        if "text" in formats:
            formats["text"].decode("utf-8")
            if b"\0" in formats["text"]:
                raise ValueError("embedded NUL")
        result = Snapshot(formats, [], self.stamp, self.sequence)
        if not hmac.compare_digest(result.digest(), self.digest):
            raise ValueError("clipboard integrity failure")
        self.buffers.clear()
        return result
