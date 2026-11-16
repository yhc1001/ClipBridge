"""Apply the narrow Windows Korean F2 half-duplex fix to pinned 1.27.0 source."""
from pathlib import Path

HEADER = Path(__file__).with_name("windows_hangul_tap.h")
INCLUDE_BEFORE = '#include "platform/MSWindowsComputer.h"\n'
INCLUDE_AFTER = INCLUDE_BEFORE + '#include "ClipBridgeHangulTap.h"\n'
BEFORE = """    if (key != kKeyNone) {
      // do it
      m_keyState->sendKeyEvent(
"""

AFTER = """    // Some Korean keyboards emit a VK_HANGUL down with scan code F2
    // but no physical key-up. Send a complete tap for this specific key so
    // the client and downstream applications do not retain a stuck key.
    // Normal Korean 0x38, Alt, Shift+Space and non-Korean layouts are left
    // alone; on keyboards that do send F2 key-up the later release is ignored.
    if (m_isPrimary && clipbridge::normalize_korean_f2(key == kKeyHangul, button, down,
        [&](bool press) { m_keyState->sendKeyEvent(getEventTarget(), press, false, key, mask, 1, button); },
        [&]() { m_keyState->onKey(button, false, state); m_keyState->testAutoRepeat(false, false, button); })) {
      return true;
    }
    if (key != kKeyNone) {
      // do it
      m_keyState->sendKeyEvent(
"""


def apply(source: Path):
    target = source / "src/lib/platform/MSWindowsComputer.cpp"
    header = target.with_name("ClipBridgeHangulTap.h")
    expected_header = HEADER.read_bytes()
    if header.exists() and header.read_bytes() != expected_header:
        raise ValueError("Unexpected Deskflow helper; refusing to overwrite")
    text = target.read_text(encoding="utf-8")
    if text.count(AFTER) == 1 and text.count(INCLUDE_AFTER) == 1 and BEFORE not in text.replace(AFTER, ""):
        header.write_bytes(expected_header)
        return  # Identical patch is already applied.
    if text.count(BEFORE) != 1 or text.count(INCLUDE_BEFORE) != 1 or AFTER in text or INCLUDE_AFTER in text:
        raise ValueError("Unexpected Deskflow source; refusing to patch")
    modified = text.replace(INCLUDE_BEFORE, INCLUDE_AFTER, 1).replace(BEFORE, AFTER, 1)
    header.write_bytes(expected_header)
    target.write_text(modified, encoding="utf-8", newline="\n")
