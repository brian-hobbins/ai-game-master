"""SQLite persistence for game sessions.

Standard-library sqlite3 only. The entire game state (party, threats, map,
scene, and the full narrative log) is stored as JSON in one row per game, so a
turn is one small write and a server restart or crash never loses a campaign.

Safe by design: init_db() only CREATEs IF NOT EXISTS — it never drops or clears
data on startup (a lesson learned the hard way on a sibling project).
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

from engine.state import (Character, Event, Feature, GameMap, GameState,
                          Monster, Scene)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "aigm.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with _connect() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS games(
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ruleset     TEXT NOT NULL,
                human       TEXT,
                adventure   TEXT,
                state_json  TEXT NOT NULL,
                options_json TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            """
        )


def create_game(ruleset_id: str, human: str, adventure: str,
                state: GameState, options: list[str]) -> int:
    now = _now()
    with _connect() as c:
        cur = c.execute(
            "INSERT INTO games(ruleset, human, adventure, state_json, options_json,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
            (ruleset_id, human, adventure, json.dumps(asdict(state)),
             json.dumps(options or []), now, now),
        )
        return cur.lastrowid


def save_game(game_id: int, state: GameState, options: list[str]) -> None:
    with _connect() as c:
        c.execute(
            "UPDATE games SET state_json=?, options_json=?, updated_at=? WHERE id=?",
            (json.dumps(asdict(state)), json.dumps(options or []), _now(), game_id),
        )


def load_latest() -> dict | None:
    with _connect() as c:
        row = c.execute(
            "SELECT * FROM games ORDER BY updated_at DESC, id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"], "ruleset": row["ruleset"], "human": row["human"],
        "adventure": row["adventure"],
        "state": rebuild_state(json.loads(row["state_json"])),
        "options": json.loads(row["options_json"] or "[]"),
    }


# -- reconstruct dataclasses from stored JSON --------------------------------

def _only(cls, d: dict) -> dict:
    """Keep only keys that are fields of `cls` (forward-compatible loads)."""
    valid = getattr(cls, "__dataclass_fields__", {})
    return {k: v for k, v in (d or {}).items() if k in valid}


def rebuild_state(d: dict) -> GameState:
    gm = d.get("map", {}) or {}
    game_map = GameMap(
        width=gm.get("width", 12), height=gm.get("height", 8),
        biome=gm.get("biome", "dungeon"),
        features=[Feature(**_only(Feature, f)) for f in gm.get("features", []) or []],
    )
    scene = Scene(**_only(Scene, d.get("scene", {})))
    state = GameState(
        ruleset=d.get("ruleset", "cairn"),
        adventure=d.get("adventure", ""),
        scene=scene, map=game_map,
        party=[Character(**_only(Character, c)) for c in d.get("party", []) or []],
        threats=[Monster(**_only(Monster, m)) for m in d.get("threats", []) or []],
        log=[Event(**_only(Event, e)) for e in d.get("log", []) or []],
        in_combat=d.get("in_combat", False),
        round=d.get("round", 0),
    )
    return state
