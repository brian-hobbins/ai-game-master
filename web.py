#!/usr/bin/env python3
"""Web front end: a multiplayer virtual tabletop for the AI Warden.

    python3 web.py            # then open http://127.0.0.1:8099

Several humans share one table in their own browsers; each claims a character
and plays it, and **every unclaimed seat is played by the AI**. An AI Warden
runs the world, the monsters, and any AI-held party members. A round-robin
spotlight keeps turns orderly; clients poll /api/state to stay in sync. The
whole game (and its narrative log) is persisted to SQLite, so restarts and
crashes never lose a campaign.

Backend for the Warden: AIGM_BACKEND = cli (default, your `claude` sub) | api.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from engine.dice import Dice
from engine.session import Session
from engine.state import GameState
from engine import store
from gm.client import LLMError, get_client
from gm.warden import Warden
from rulesets import available, load_ruleset

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("AIGM_HOST", "127.0.0.1")
PORT = int(os.environ.get("AIGM_PORT", "8099"))


class Table:
    """A shared, persisted game table. Humans claim seats; the AI plays the
    rest. A spotlight cursor (self.turn) tracks whose turn it is."""
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()
        try:
            store.init_db()
            self._resume()
        except Exception as exc:
            print(f"(resume skipped: {exc})")

    def reset(self):
        self.session: Session | None = None
        self.ruleset = None
        self.human = ""
        self.last_options: list[str] = []
        self.started = False
        self.game_id: int | None = None
        self.owners: dict[str, str] = {}   # character name -> player_id (human-controlled)
        self.seen: dict[str, float] = {}   # player_id -> last-activity epoch
        self.turn = 0                      # spotlight: index into party

    SEAT_TTL = 60.0   # a claimed seat frees up after this many idle seconds

    def _touch(self, player_id):
        if player_id:
            self.seen[player_id] = time.time()

    # -- seat / turn helpers ------------------------------------------------
    def _party(self):
        return self.session.state.party if self.session else []

    def _claimed_names(self) -> set[str]:
        return set(self.owners.keys())

    def _seats_of(self, pid) -> list[str]:
        return [n for n, p in self.owners.items() if p == pid]

    def _sync_ai_flags(self):
        for pc in self._party():
            pc.is_ai = pc.name not in self.owners   # unclaimed seat => AI plays it

    def _living_indices(self):
        return [i for i, c in enumerate(self._party()) if c.alive()]

    def _active_idx(self):
        li = self._living_indices()
        if not li:
            return None
        if self.turn in li:
            return self.turn
        for i in li:
            if i >= self.turn:
                return i
        return li[0]

    def _advance(self):
        li = self._living_indices()
        if not li:
            return
        cur = self._active_idx()
        self.turn = li[(li.index(cur) + 1) % len(li)]

    # -- commands -----------------------------------------------------------
    def new_game(self, *, name, premise, companions, ruleset_id, seed, backend,
                 player_id, party_size=4):
        ruleset = load_ruleset(ruleset_id or "cairn")
        client = get_client(backend)
        dice = Dice(seed if seed not in ("", None) else None)
        state = GameState(ruleset=ruleset.id, adventure=premise or "")
        party = [ruleset.create_character(dice, name or "Bea", is_ai=False)]
        for cname, persona in _parse_companions(companions):
            party.append(ruleset.create_character(dice, cname, is_ai=True, persona=persona))
        # fill the rest of the party with AI companions so you never adventure alone
        try:
            size = max(1, min(6, int(party_size)))
        except (TypeError, ValueError):
            size = 4
        used = {p.name.lower() for p in party}
        for cname, persona in _AUTO_COMPANIONS:
            if len(party) >= size:
                break
            if cname.lower() in used:
                continue
            party.append(ruleset.create_character(dice, cname, is_ai=True, persona=persona))
            used.add(cname.lower())
        for i, pc in enumerate(party):
            pc.x, pc.y = 1, 2 + i
        state.party = party
        self.session = Session(state, Warden(client, ruleset), ruleset, dice)
        self.ruleset = ruleset
        self.human = party[0].name
        self.started = True
        pid = player_id or uuid.uuid4().hex
        self.owners = {party[0].name: pid}     # creator holds seat 0
        self.turn = 0
        self._sync_ai_flags()
        opening = self.session.begin(premise or "Begin the adventure.")
        self.last_options = opening.get("options", []) or []
        self.game_id = store.create_game(ruleset.id, self.human, premise or "",
                                         self.session.state, self.last_options)
        return {"player_id": pid, "seat": party[0].name,
                "beats": [self._beat(self.human, None, opening, opening=True)],
                "state": self.snapshot(pid)}

    def join(self, player_id, name=""):
        """Passive join (page load / poll). Auto-claims ONLY the primary host
        seat — companion seats are left to the AI and are never grabbed here.
        That keeps solo play safe: opening a second tab/window makes you a
        spectator instead of silently turning an AI companion human. A real
        second player takes over a companion explicitly via claim()."""
        if not self.session:
            raise LLMError("No game in progress.")
        pid = player_id or uuid.uuid4().hex
        self._touch(pid)
        mine = self._seats_of(pid)
        if mine:                                     # same player (e.g. a refresh)
            seat = self.human if self.human in mine else mine[0]
        else:
            seat = self._auto_host_seat(pid)
        return {"player_id": pid, "seat": seat, "spectator": seat is None,
                "state": self.snapshot(pid)}

    def _auto_host_seat(self, pid):
        """Give `pid` the host seat if it's free, or reclaim it if its holder
        has gone idle past SEAT_TTL. Returns the seat name, or None."""
        host = self.human
        if not host or not any(c.name == host and c.alive() for c in self._party()):
            return None
        holder = self.owners.get(host)
        if holder is not None and holder != pid:
            if (time.time() - self.seen.get(holder, 0)) <= self.SEAT_TTL:
                return None                          # host seat actively held
        self.owners[host] = pid                      # claim / reclaim the host seat
        self._sync_ai_flags()
        self._save()
        return host

    def claim(self, player_id, name):
        """Switch a character to PLAYER control (human). A player may hold
        several characters at once — so a solo tester can play the whole party,
        or toggle individual companions between AI and themselves."""
        if not self.session:
            raise LLMError("No game in progress.")
        pid = player_id or uuid.uuid4().hex
        self._touch(pid)
        target = next((c for c in self._party() if c.name == name and c.alive()), None)
        if not target:
            raise LLMError(f"No such character: {name}.")
        holder = self.owners.get(name)
        if holder is not None and holder != pid \
                and (time.time() - self.seen.get(holder, 0)) <= self.SEAT_TTL:
            raise LLMError(f"{name} is already being played by someone else.")
        self.owners[name] = pid                      # take control (keeps other seats)
        self._sync_ai_flags()
        self._save()
        return {"player_id": pid, "seat": name, "spectator": False,
                "state": self.snapshot(pid)}

    def release(self, player_id, name):
        """Switch a character back to AI control. You can release a seat you
        hold (or any seat, if you're the host, to hand it to the Warden)."""
        if not self.session:
            raise LLMError("No game in progress.")
        pid = player_id or uuid.uuid4().hex
        self._touch(pid)
        holder = self.owners.get(name)
        if holder is None:
            raise LLMError(f"{name} is already AI-controlled.")
        is_host = self.human in self._seats_of(pid)
        if holder != pid and not is_host:
            raise LLMError(f"You don't control {name}.")
        del self.owners[name]
        self._sync_ai_flags()
        # if that handed the AI the current spotlight, let it play straight away
        beats = self._auto_run_ai() if self.session.warden else []
        self._save()
        return {"player_id": pid, "seat": name, "released": True,
                "beats": beats, "state": self.snapshot(pid)}

    def leave(self, player_id):
        if player_id in self.owners.values():
            self.owners = {n: p for n, p in self.owners.items() if p != player_id}
            self._sync_ai_flags()
            self._save()
        return {"state": self.snapshot(player_id)}

    def action(self, player_id, text):
        if not self.session:
            raise LLMError("No game in progress.")
        self._touch(player_id)
        idx = self._active_idx()
        if idx is None:
            raise LLMError("The party has fallen.")
        active = self._party()[idx]
        if self.owners.get(active.name) != player_id:
            raise LLMError(f"It's not your turn — waiting for {active.name}.")
        out = self.session.take_turn(active.name, text)
        self.last_options = out.get("options", []) or []
        beats = [self._beat(active.name, text, out)]
        self._advance()
        beats += self._auto_run_ai()
        self._save()
        return {"beats": beats, "state": self.snapshot(player_id)}

    def _auto_run_ai(self):
        """Let AI-held seats take their turns until the spotlight lands on a
        human-held seat (or the party falls). Safe to call any time."""
        beats = []
        for _ in range(len(self._party())):
            ai = self._active_idx()
            if ai is None:
                break
            seat = self._party()[ai]
            if seat.name in self.owners:      # a human holds this seat: wait
                break
            aout = self.session.ai_turn(seat)
            dec = aout.get("ai_decision", {})
            beats.append(self._beat(seat.name, dec.get("action", ""), aout,
                                    ai_say=dec.get("say", "")))
            self.last_options = aout.get("options", []) or self.last_options
            self._advance()
        return beats

    def move(self, player_id, name, x, y):
        if not self.session:
            raise LLMError("No game in progress.")
        tok = self.session.state.combatant(name)
        if tok is None:
            return {"state": self.snapshot(player_id)}
        tok.x, tok.y = self.session._clamp(x, y)
        self._save()
        return {"state": self.snapshot(player_id)}

    # -- persistence --------------------------------------------------------
    def _save(self):
        if self.session and self.game_id is not None:
            try:
                store.save_game(self.game_id, self.session.state, self.last_options)
            except Exception as exc:
                print(f"(save failed: {exc})")

    def _resume(self):
        row = store.load_latest()
        if not row:
            return
        ruleset = load_ruleset(row["ruleset"])
        client = get_client()
        self.session = Session(row["state"], Warden(client, ruleset), ruleset, Dice())
        self.ruleset = ruleset
        self.human = row["human"] or (row["state"].party[0].name if row["state"].party else "")
        self.last_options = row["options"]
        self.game_id = row["id"]
        self.started = True
        self.owners = {}          # players re-join after a restart
        self.turn = 0
        self._sync_ai_flags()     # everyone AI until humans re-claim seats
        print(f"(resumed game #{self.game_id}: {self.human} — {row['adventure'][:48]})")

    # -- serialization ------------------------------------------------------
    def _beat(self, actor, action, out, *, ai_say="", opening=False):
        return {"actor": actor, "action": action, "opening": opening, "ai_say": ai_say,
                "narration": out.get("narration", ""),
                "options": out.get("options", []) or [],
                "mechanics": [m.get("detail", "") for m in out.get("results", []) if m.get("detail")]}

    def snapshot(self, player_id=None):
        if not self.session:
            return {"started": False}
        self._touch(player_id)          # polling keeps an active player's seat alive
        st = self.session.state
        claimed = self._claimed_names()
        idx = self._active_idx()
        active = self._party()[idx].name if idx is not None else None
        my_seats = self._seats_of(player_id) if player_id else []
        your_seat = (self.human if self.human in my_seats else my_seats[0]) if my_seats else None
        party = []
        for c in st.party:
            d = asdict(c)
            d["controlled"] = "human" if c.name in self.owners else "ai"
            d["is_you"] = (c.name in my_seats)
            party.append(d)
        return {
            "started": True,
            "ruleset": {"id": self.ruleset.id, "name": self.ruleset.name,
                        "warden_title": self.ruleset.warden_title,
                        "abilities": self.ruleset.abilities,
                        "attribution": self.ruleset.attribution},
            "human": self.human,
            "adventure": st.adventure,
            "scene": asdict(st.scene),
            "map": asdict(st.map),
            "party": party,
            "threats": [asdict(m) for m in st.threats if m.alive()],
            "in_combat": st.in_combat,
            "round": st.round,
            "options": self.last_options,
            "log": [asdict(e) for e in st.log],
            "party_down": not bool(st.living_party()),
            "active": active,
            "active_is_ai": (active is not None and active not in claimed),
            "your_seat": your_seat,
            "your_seats": my_seats,
            "your_turn": bool(active and active in my_seats),
            "players": len(set(self.owners.values())),
        }


_AUTO_COMPANIONS = [
    ("Thorn", "gruff dwarf sellsword; blunt, brave, first into a fight"),
    ("Mira", "wary elven scout; cautious, sharp-eyed, scouts ahead"),
    ("Bram", "cheerful halfling cook turned fighter; loyal and steady"),
    ("Sable", "quiet human rogue with a dark past; picks locks, trusts no one"),
    ("Edda", "devout cleric; tends the wounded, hates the undead"),
    ("Gorm", "stoic half-orc guard; few words, immovable in a doorway"),
]


def _parse_companions(s):
    out = []
    for chunk in (s or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        cname, _, persona = chunk.partition(":")
        out.append((cname.strip(), persona.strip()))
    return out


TABLE = Table()


class Handler(BaseHTTPRequestHandler):
    server_version = "AIWarden/0.3"

    def log_message(self, *a):
        return

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "web", "index.html"), "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._json(500, {"error": "web/index.html missing"})
        if url.path == "/api/health":
            return self._json(200, {"ok": True, "rulesets": available()})
        if url.path == "/api/rulesets":
            return self._json(200, {"rulesets": available()})
        if url.path == "/api/state":
            pid = (parse_qs(url.query).get("player_id", [""])[0]) or None
            with TABLE.lock:
                return self._json(200, TABLE.snapshot(pid))
        self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            payload = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid JSON"})
        pid = payload.get("player_id") or None
        try:
            if self.path == "/api/new":
                with TABLE.lock:
                    return self._json(200, TABLE.new_game(
                        name=payload.get("name", "").strip(),
                        premise=payload.get("premise", "").strip(),
                        companions=payload.get("companions", "").strip(),
                        ruleset_id=payload.get("ruleset", "cairn"),
                        seed=payload.get("seed"), backend=payload.get("backend"),
                        player_id=pid, party_size=payload.get("party_size", 4)))
            if self.path == "/api/join":
                with TABLE.lock:
                    return self._json(200, TABLE.join(pid, payload.get("name", "").strip()))
            if self.path == "/api/claim":
                with TABLE.lock:
                    return self._json(200, TABLE.claim(pid, payload.get("name", "").strip()))
            if self.path == "/api/release":
                with TABLE.lock:
                    return self._json(200, TABLE.release(pid, payload.get("name", "").strip()))
            if self.path == "/api/leave":
                with TABLE.lock:
                    return self._json(200, TABLE.leave(pid))
            if self.path == "/api/action":
                text = (payload.get("action") or "").strip()
                if not text:
                    return self._json(400, {"error": "action is required"})
                with TABLE.lock:
                    return self._json(200, TABLE.action(pid, text))
            if self.path == "/api/move":
                with TABLE.lock:
                    return self._json(200, TABLE.move(pid, payload.get("name", ""),
                                                      payload.get("x", 0), payload.get("y", 0)))
        except LLMError as exc:
            return self._json(502, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        self._json(404, {"error": "not found"})


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"AI Warden VTT -> http://{HOST}:{PORT}   (multiplayer; Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
