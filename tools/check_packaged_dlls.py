"""Check imported symbols against the exact libraries selected by PyInstaller."""
import ast
from pathlib import Path
import pefile

root = Path(__file__).resolve().parents[1]
analysis = ast.literal_eval((root / "build" / "ClipBridge" / "Analysis-00.toc").read_text(encoding="utf-8"))
libraries = {}
for group in analysis:
    if isinstance(group, list):
        for row in group:
            if isinstance(row, tuple) and len(row) == 3 and row[2] in ("BINARY", "EXTENSION"):
                libraries.setdefault(Path(row[0]).name.lower(), Path(row[1]))
exports = {}
for name in ("qtcore.pyd", "qt6core.dll", "pyside6.abi3.dll", "shiboken6.abi3.dll"):
    source = libraries[name]
    parsed = pefile.PE(str(source), max_symbol_exports=65536)
    for imported in parsed.DIRECTORY_ENTRY_IMPORT:
        target_name = imported.dll.decode().lower()
        target = libraries.get(target_name)
        if not target:
            continue
        if target_name not in exports:
            target_pe = pefile.PE(str(target), max_symbol_exports=65536)
            exports[target_name] = {item.name for item in getattr(target_pe, "DIRECTORY_ENTRY_EXPORT").symbols}
        missing = [item.name.decode() for item in imported.imports if item.name and item.name not in exports[target_name]]
        if missing:
            print(name, "->", target_name, "missing:", missing)
