"""Tests for guest list persistence and singer formatting."""

from biaoke.lib.guest_manager import GuestManager, format_guest_names, split_guest_names


def test_guest_manager_persists_names(tmp_path):
    manager = GuestManager(tmp_path / "guests.json")

    ok, _ = manager.add_guest(" Ana ")
    assert ok is True

    loaded = GuestManager(tmp_path / "guests.json")
    assert loaded.list_guests() == ["Ana"]


def test_guest_manager_rejects_duplicate_case_insensitive(tmp_path):
    manager = GuestManager(tmp_path / "guests.json")

    assert manager.add_guest("Ana")[0] is True
    assert manager.add_guest("ana")[0] is False
    assert manager.list_guests() == ["Ana"]


def test_format_guest_names_allows_multiple_singers():
    assert split_guest_names("Ana, Joao + Maria; Ana") == ["Ana", "Joao", "Maria"]
    assert format_guest_names("Ana, Joao + Maria") == "Ana + Joao + Maria"
    assert format_guest_names("", fallback="Biaoke") == "Biaoke"
