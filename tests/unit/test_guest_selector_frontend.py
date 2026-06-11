"""Regression checks for the guest selector frontend contract."""

from pathlib import Path


BASE_TEMPLATE = Path("biaoke/templates/base.html")
PREPARE_TEMPLATE = Path("biaoke/templates/prepare.html")
FILES_TEMPLATE = Path("biaoke/templates/files.html")
SPA_NAVIGATION = Path("biaoke/static/spa-navigation.js")


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


def test_host_user_uses_dedicated_cookie_and_recovers_from_old_guest_state():
    source = BASE_TEMPLATE.read_text()
    host_block = _function_block(source, "setHostUserCookie")
    get_block = _function_block(source, "getUserCookie")
    block = _function_block(source, "setUserCookie")

    assert "biaoke_host_user" in source
    assert "window.BIAOKE_HOST_USER_COOKIE" in host_block
    assert 'Cookies.set("user", cleanName' in host_block
    assert 'if ($(".guest-selection-panel").length) return "";' in get_block
    assert "looksLikeStoredGuestSelection(legacyUser)" in get_block
    assert "setHostUserCookie(name)" in block


def test_prepare_youtube_uses_guest_selector_for_current_song_only():
    source = PREPARE_TEMPLATE.read_text()
    assert "song_added_by: getSelectedSingers(this)" in source
    assert "song_added_by: getUserCookie() || \"\"" not in source


def test_successful_guest_action_clears_selected_singers():
    prepare_source = PREPARE_TEMPLATE.read_text()
    files_source = FILES_TEMPLATE.read_text()

    assert "clearSelectedSingers(button)" in prepare_source
    assert "clearSelectedSingers(e.currentTarget)" in files_source
    assert "function clearSelectedSingers" in BASE_TEMPLATE.read_text()


def test_navbar_user_change_updates_host_cookie():
    source = SPA_NAVIGATION.read_text()

    assert "setHostUserCookie(cleanName)" in source
    assert 'Cookies.set(window.BIAOKE_HOST_USER_COOKIE || "biaoke_host_user"' in source
