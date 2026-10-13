from __future__ import annotations

import io
import struct
import warnings
from PIL import Image

Image.MAX_IMAGE_PIXELS = 25_000_000


def dib_image(data: bytes) -> Image.Image:
    if len(data) < 40:
        raise ValueError("short DIB")
    size, width, height, planes, bits, compression = struct.unpack_from("<IiiHHI", data)
    if size not in (40, 52, 56, 108, 124) or len(data) < size or width <= 0 or not 0 < abs(height) <= 25000 or width * abs(height) > Image.MAX_IMAGE_PIXELS:
        raise ValueError("invalid DIB dimensions")
    if planes != 1 or bits not in (1, 4, 8, 16, 24, 32) or compression not in (0, 3, 6):
        raise ValueError("unsupported DIB compression")
    colors = struct.unpack_from("<I", data, 32)[0]
    if colors > 256:
        raise ValueError("invalid palette")
    masks = (16 if compression == 6 else 12) if size == 40 and compression in (3, 6) else 0
    offset = size + masks + (colors or (1 << bits if bits <= 8 else 0)) * 4
    stride = ((width * bits + 31) // 32) * 4
    if offset + stride * abs(height) > len(data):
        raise ValueError("truncated DIB")
    bmp = struct.pack("<2sIHHI", b"BM", 14 + len(data), 0, 0, 14 + offset) + data
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image = Image.open(io.BytesIO(bmp))
        image.load()
    return image.convert("RGBA")


def png_image(data: bytes) -> Image.Image:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PNG")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image = Image.open(io.BytesIO(data))
        if image.format != "PNG":
            raise ValueError("not PNG")
        image.load()
    return image.convert("RGBA")


def image_formats(image: Image.Image) -> dict[str, bytes]:
    image = image.convert("RGBA")
    png, bmp = io.BytesIO(), io.BytesIO()
    image.save(png, "PNG")
    image.convert("RGB").save(bmp, "BMP")
    header = bytearray(124)
    struct.pack_into("<IiiHHIIiiII", header, 0, 124, image.width, -image.height, 1, 32, 3, image.width * image.height * 4, 0, 0, 0, 0)
    struct.pack_into("<IIIII", header, 40, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000, 0x73524742)
    struct.pack_into("<I", header, 108, 4)
    return {"PNG": png.getvalue(), "DIB": bmp.getvalue()[14:], "DIBV5": bytes(header) + image.tobytes("raw", "BGRA")}


def normalize(formats: dict[str, bytes], limit: int, *, incoming=False):
    result = dict(formats)
    image = None
    for name in ("PNG", "DIBV5", "DIB"):
        if name in result:
            try:
                decoded = png_image(result[name]) if name == "PNG" else dib_image(result[name])
                image = image or decoded
            except Exception:
                if incoming:
                    raise ValueError("invalid image") from None
                del result[name]
    if image:
        generated = image_formats(image)
        # Preserve raw source representations when valid. PNG-only clips also get a pasteable DIB.
        for name, data in generated.items():
            if name not in result and sum(map(len, result.values())) + len(data) <= limit:
                result[name] = data
    if sum(map(len, result.values())) > limit:
        raise ValueError("clipboard size limit")
    return result
