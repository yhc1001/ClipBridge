from tools.hangul_key_probe import event_text, is_target


def test_only_language_and_alt_events_are_recorded():
    for vk in (0x15, 0x19, 0x12, 0xA4, 0xA5):
        assert is_target(vk, 0x38)
    assert is_target(0xE5, 0xF2)
    assert not is_target(ord("A"), 0x1E)
    assert not is_target(ord("A"), 0x38)
    assert not is_target(0xE5, 0x1E)


def test_event_reports_injection_and_release_without_text_content():
    line = event_text(0x15, 0xF2, 0x10, 0x101, 2.1)
    assert "뗌" in line and "프로그램에서 전달" in line
    assert "15" in line and "F2" in line
