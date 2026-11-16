#include "../tools/windows_hangul_tap.h"
#include <cassert>
#include <vector>

int main()
{
  std::vector<bool> events;
  int resets = 0;
  const auto emit = [&](bool down) { events.push_back(down); };
  const auto reset = [&]() { ++resets; };

  // Three actual presses, with the release events absent as on the user's
  // keyboard, must produce three complete taps rather than held/repeat keys.
  for (int i = 0; i < 3; ++i) {
    assert(clipbridge::normalize_korean_f2(true, 0x1f2, true, emit, reset));
  }
  assert((events == std::vector<bool>{true, false, true, false, true, false}));
  assert(resets == 3);

  // An eventual genuine F2 release is consumed: no extra toggle or reset.
  assert(clipbridge::normalize_korean_f2(true, 0x1f2, false, emit, reset));
  assert(events.size() == 6 && resets == 3);

  // A Korean key at 0x38, ordinary Alt and any other key take the original
  // path. Test both press and release so modifiers keep their usual behavior.
  for (bool down : {false, true}) {
    assert(!clipbridge::normalize_korean_f2(true, 0x138, down, emit, reset));
    assert(!clipbridge::normalize_korean_f2(false, 0x1f2, down, emit, reset));
    assert(!clipbridge::normalize_korean_f2(false, 0x138, down, emit, reset));
  }
  assert(events.size() == 6 && resets == 3);
}
