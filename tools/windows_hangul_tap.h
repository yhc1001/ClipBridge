// Korean F2 keyboards can send key-down without key-up. This helper is
// intentionally independent of the Windows API so its event policy is tested.
#pragma once

namespace clipbridge {
template <class Emit, class Reset>
bool normalize_korean_f2(bool is_hangul, unsigned int button, bool down, Emit emit, Reset reset)
{
  if (!is_hangul || (button & 0xffu) != 0xf2u) {
    return false;
  }
  if (down) {
    emit(true);
    emit(false);
    reset();
  }
  return true;
}
} // namespace clipbridge
