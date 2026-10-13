"""Bridge macOS public.html and Windows CF_HTML byte offsets."""
import re


def html_to_cfhtml(data: bytes) -> bytes:
    data = data.rstrip(b"\0")
    data.decode("utf-8")
    body = re.search(br"<body\b[^>]*>(.*?)</body\s*>", data, re.I | re.S)
    fragment = body.group(1) if body else data
    before, after = b"<html><body><!--StartFragment-->", b"<!--EndFragment--></body></html>"
    context = before + fragment + after
    template = "Version:1.0\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n"
    start = len(template.format(0, 0, 0, 0).encode("ascii"))
    header = template.format(start, start + len(context), start + len(before), start + len(before) + len(fragment)).encode("ascii")
    return header + context


def cfhtml_to_html(data: bytes) -> bytes:
    data = data.rstrip(b"\0")
    start, end = re.search(br"(?m)^StartHTML:\s*(-?\d+)", data[:2048]), re.search(br"(?m)^EndHTML:\s*(-?\d+)", data[:2048])
    if start and end and 0 <= int(start[1]) <= int(end[1]) <= len(data):
        data = data[int(start[1]):int(end[1])]
    elif data.startswith(b"Version:"):
        start, end = re.search(br"(?m)^StartFragment:\s*(\d+)", data[:2048]), re.search(br"(?m)^EndFragment:\s*(\d+)", data[:2048])
        if not start or not end or not 0 <= int(start[1]) <= int(end[1]) <= len(data):
            raise ValueError("invalid HTML offsets")
        data = data[int(start[1]):int(end[1])]
    data.decode("utf-8")
    return data
