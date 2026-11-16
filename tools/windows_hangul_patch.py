"""Apply the narrow Windows Korean F2 half-duplex fix to pinned 1.27.0 source."""
from pathlib import Path

BEFORE = """    if (key != kKeyNone) {
      // do it
      m_keyState->sendKeyEvent(
"""

AFTER = """    // Some Korean keyboards emit a VK_HANGUL down with scan code F2
    // but no physical key-up. Send a complete tap for this specific key so
    // the client and downstream applications do not retain a stuck key.
    // Normal Korean 0x38, Alt, Shift+Space and non-Korean layouts are left
    // alone; on keyboards that do send F2 key-up the later release is ignored.
    if (key == kKeyHangul && (button & 0xffu) == 0xf2u) {
      if (down) {
        m_keyState->sendKeyEvent(getEventTarget(), true, false, key, mask, 1, button);
        m_keyState->sendKeyEvent(getEventTarget(), false, false, key, mask, 1, button);
        m_keyState->onKey(button, false, state);
        m_keyState->testAutoRepeat(false, false, button);
      }
      return true;
    }
    if (key != kKeyNone) {
      // do it
      m_keyState->sendKeyEvent(
"""


def apply(source: Path):
    target = source / "src/lib/platform/MSWindowsComputer.cpp"
    text = target.read_text(encoding="utf-8")
    if text.count(AFTER) == 1 and BEFORE not in text.replace(AFTER, ""):
        return  # Identical patch is already applied.
    if text.count(BEFORE) != 1 or AFTER in text:
        raise ValueError("Unexpected Deskflow source; refusing to patch")
    target.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8", newline="\n")
