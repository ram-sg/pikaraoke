"""Persistent guest list used by the stage queue UI."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from biaoke.lib.get_platform import get_data_directory


GUEST_SEPARATOR = " + "


def split_guest_names(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Parse guest names from a string or sequence and remove duplicates."""
    if value is None:
        raw_parts: list[str] = []
    elif isinstance(value, str):
        raw_parts = value.replace(";", ",").replace("+", ",").split(",")
    else:
        raw_parts = [str(item) for item in value]

    names: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        name = " ".join(str(raw or "").strip().split())
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name[:80])
    return names


def format_guest_names(value: str | list[str] | tuple[str, ...] | None, fallback: str = "") -> str:
    """Return the display label stored in queue items."""
    names = split_guest_names(value)
    if names:
        return GUEST_SEPARATOR.join(names)
    return " ".join(str(fallback or "").strip().split())


class GuestManager:
    """Stores guest names in a small JSON file under the app data directory."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(get_data_directory()) / "guests.json"

    def list_guests(self) -> list[str]:
        """Return saved guests sorted by insertion order."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("Could not read guest list %s: %s", self.path, exc)
            return []
        if isinstance(data, dict):
            data = data.get("guests", [])
        if not isinstance(data, list):
            return []
        return split_guest_names([str(item) for item in data])

    def add_guest(self, name: str) -> tuple[bool, str]:
        """Add one guest name."""
        parsed = split_guest_names(name)
        if not parsed:
            return False, "Nome vazio."
        guest = parsed[0]
        guests = self.list_guests()
        if guest.casefold() in {item.casefold() for item in guests}:
            return False, "Guest ja existe."
        guests.append(guest)
        self._write(guests)
        return True, "Guest adicionado."

    def remove_guest(self, name: str) -> tuple[bool, str]:
        """Remove one guest name."""
        target = split_guest_names(name)
        if not target:
            return False, "Nome vazio."
        target_key = target[0].casefold()
        guests = [guest for guest in self.list_guests() if guest.casefold() != target_key]
        if len(guests) == len(self.list_guests()):
            return False, "Guest nao encontrado."
        self._write(guests)
        return True, "Guest removido."

    def _write(self, guests: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"guests": split_guest_names(guests)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
