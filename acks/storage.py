"""SQLite persistence. Each character is one row holding its JSON sheet."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .character import Character

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    owner_id   INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    data       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_char_owner ON characters (guild_id, owner_id);
CREATE TABLE IF NOT EXISTS encounters (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    data       TEXT    NOT NULL,
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (guild_id, channel_id)
);
CREATE TABLE IF NOT EXISTS active_characters (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- characters --------------------------------------------------------
    def create(self, ch: Character) -> Character:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO characters (guild_id, owner_id, name, data) VALUES (?, ?, ?, ?)",
                (ch.data["guild_id"], ch.data["owner_id"], ch.name, json.dumps(ch.data)))
            self._conn.commit()
            ch.id = cur.lastrowid
        return ch

    def save(self, ch: Character) -> None:
        if ch.id is None:
            self.create(ch)
            return
        with self._lock:
            self._conn.execute(
                "UPDATE characters SET name = ?, data = ?, owner_id = ?, updated_at = datetime('now') WHERE id = ?",
                (ch.name, json.dumps(ch.data), ch.data["owner_id"], ch.id))
            self._conn.commit()

    def get(self, char_id: int) -> Character | None:
        with self._lock:
            row = self._conn.execute("SELECT id, data FROM characters WHERE id = ?", (char_id,)).fetchone()
        return Character(json.loads(row["data"]), row["id"]) if row else None

    def delete(self, char_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM characters WHERE id = ?", (char_id,))
            self._conn.execute("DELETE FROM active_characters WHERE character_id = ?", (char_id,))
            self._conn.commit()

    def list_for_user(self, guild_id: int, user_id: int) -> list[Character]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, data FROM characters WHERE guild_id = ? AND owner_id = ? ORDER BY name",
                (guild_id, user_id)).fetchall()
        return [Character(json.loads(r["data"]), r["id"]) for r in rows]

    def list_for_guild(self, guild_id: int) -> list[Character]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, data FROM characters WHERE guild_id = ? ORDER BY name", (guild_id,)).fetchall()
        return [Character(json.loads(r["data"]), r["id"]) for r in rows]

    # -- active character --------------------------------------------------
    def set_active(self, guild_id: int, user_id: int, char_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO active_characters (guild_id, user_id, character_id) VALUES (?, ?, ?) "
                "ON CONFLICT (guild_id, user_id) DO UPDATE SET character_id = excluded.character_id",
                (guild_id, user_id, char_id))
            self._conn.commit()

    def get_active(self, guild_id: int, user_id: int) -> Character | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT character_id FROM active_characters WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)).fetchone()
        if row:
            ch = self.get(row["character_id"])
            if ch:
                return ch
        chars = self.list_for_user(guild_id, user_id)
        if len(chars) == 1:
            return chars[0]
        return None

    def active_character_ids(self, guild_id: int) -> set[int]:
        """Every player's active character in a server (used to pre-fill the party)."""
        with self._lock:
            rows = self._conn.execute("SELECT character_id FROM active_characters WHERE guild_id = ?",
                                      (guild_id,)).fetchall()
        return {r["character_id"] for r in rows}

    # -- encounters (one initiative roster per channel) --------------------
    def get_encounter(self, guild_id: int, channel_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM encounters WHERE guild_id = ? AND channel_id = ?",
                                     (guild_id, channel_id)).fetchone()
        return json.loads(row["data"]) if row else None

    def save_encounter(self, guild_id: int, channel_id: int, enc: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO encounters (guild_id, channel_id, data) VALUES (?, ?, ?) "
                "ON CONFLICT (guild_id, channel_id) DO UPDATE SET data = excluded.data, updated_at = datetime('now')",
                (guild_id, channel_id, json.dumps(enc)))
            self._conn.commit()

    def delete_encounter(self, guild_id: int, channel_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM encounters WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id))
            self._conn.commit()
