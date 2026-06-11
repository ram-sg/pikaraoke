"""Regression checks for the guest selector frontend contract."""

from pathlib import Path


BASE_TEMPLATE = Path("biaoke/templates/base.html")
PREPARE_TEMPLATE = Path("biaoke/templates/prepare.html")


def _function_block(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    end_candidates = [
        source.find("\n    function ", start + 1),
        source.find("\n\n    $(function", start + 1),
    ]
    end = min(candidate for candidate in end_candidates if candidate != -1)
    return source[start:end]


def test_guest_selection_does_not_overwrite_browser_user_cookie():
    source = BASE_TEMPLATE.read_text()
    block = _function_block(source, "getSelectedSingers")

    assert 'Cookies.set("user", label' not in block
    assert 'Cookies.set("user", names.join' not in block
    assert 'return names.join(" + ");' in block


def test_user_cookie_recovers_from_old_guest_selection_state():
    source = BASE_TEMPLATE.read_text()
    block = _function_block(source, "setUserCookie")

    assert "looksLikeStoredGuestSelection(user)" in block
    assert 'Cookies.set("user", name' in block


def test_prepare_youtube_uses_guest_selector_for_current_song_only():
    source = PREPARE_TEMPLATE.read_text()
    assert "song_added_by: getSelectedSingers(this)" in source
    assert "song_added_by: getUserCookie() || \"\"" not in source
