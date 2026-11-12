#!/usr/bin/env python3
"""Play a session at the terminal: you + an AI Warden (+ optional AI party).

    python3 play.py --name Bea --premise "A plague of silence grips the Wood."
    python3 play.py --name Bea --companions "Thorn:gruff dwarf sellsword;Mira:wary scout"

Backends (who runs the Warden):
    AIGM_BACKEND=cli   drive the authenticated `claude` CLI (default; your sub)
    AIGM_BACKEND=api   Anthropic SDK (needs ANTHROPIC_API_KEY)

This CLI is milestone 1 (the core loop). The same engine/Warden will back a
web/multiplayer front end next.
"""
from __future__ import annotations

import argparse
import sys

from engine.dice import Dice
from engine.session import Session
from engine.state import GameState
from gm.client import LLMError, get_client
from gm.warden import Warden
from rulesets import load_ruleset


# --- tiny terminal styling (no deps) ----------------------------------------
def _c(code): return lambda s: f"\033[{code}m{s}\033[0m"
BOLD, DIM, CYAN, YELLOW, GREEN, RED, MAG = (_c("1"), _c("2"), _c("36"),
                                            _c("33"), _c("32"), _c("31"), _c("35"))


def wrap(text: str, width: int = 88) -> str:
    import textwrap
    out = []
    for para in str(text).split("\n"):
        out.append(textwrap.fill(para, width=width) if para.strip() else "")
    return "\n".join(out)


def show_sheet(state: GameState):
    print(DIM("  ── party " + "─" * 40))
    for c in state.party:
        tag = CYAN(" [AI]") if c.is_ai else ""
        ab = " ".join(f"{k} {v}" for k, v in c.abilities.items())
        hp = GREEN(f"HP {c.hp}/{c.max_hp}") if c.hp > 0 else RED(f"HP {c.hp}/{c.max_hp}")
        st = "" if c.status == "ok" else RED(f" [{c.status}]")
        print(f"  {BOLD(c.name)}{tag}  {ab}  {hp}  Armor {c.armor}  "
              f"{c.weapon}({c.weapon_die}){st}")
    for m in state.living_threats():
        ab = " ".join(f"{k} {v}" for k, v in m.abilities.items())
        print(f"  {RED(m.name)}  {ab}  HP {m.hp}/{m.max_hp}  Armor {m.armor}")
    print(DIM("  " + "─" * 49))


def print_turn(result: dict):
    print()
    print(wrap(MAG(result.get("narration", "(the Warden is silent)"))))
    notable = [r for r in result.get("results", [])
               if r.get("kind") in ("attack", "save", "morale", "reaction")]
    for r in notable:
        print(DIM("   ⚙ " + r.get("detail", "")))
        if r.get("died"):
            print(RED(f"   ✝ {r.get('target')} is slain!"))
        elif r.get("critical"):
            print(RED(f"   ‼ {r.get('target')} suffers critical damage!"))
    opts = result.get("options") or []
    if opts:
        print()
        print(YELLOW("  You could: ") + DIM(" · ".join(opts)))


def build_party(ruleset, dice, name, companions_arg) -> list:
    party = [ruleset.create_character(dice, name, background="", is_ai=False)]
    if companions_arg:
        for chunk in companions_arg.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            cname, _, persona = chunk.partition(":")
            party.append(ruleset.create_character(
                dice, cname.strip(), is_ai=True, persona=persona.strip()))
    return party


def main() -> int:
    ap = argparse.ArgumentParser(description="Play an AI-run tabletop session.")
    ap.add_argument("--name", default=None, help="your character's name")
    ap.add_argument("--ruleset", default="cairn")
    ap.add_argument("--backend", default=None, help="cli | api | auto")
    ap.add_argument("--premise", default="The party stands at the dark edge of "
                    "the Wood, hired to find out why the village well has run black.")
    ap.add_argument("--companions", default=None,
                    help='AI party members, e.g. "Thorn:gruff dwarf;Mira:wary scout"')
    ap.add_argument("--seed", type=int, default=None, help="dice seed (reproducible)")
    args = ap.parse_args()

    name = args.name or input("Your character's name: ").strip() or "Bea"

    try:
        ruleset = load_ruleset(args.ruleset)
        client = get_client(args.backend)
    except (KeyError, LLMError) as exc:
        print(RED(f"error: {exc}"), file=sys.stderr)
        return 2

    dice = Dice(args.seed)
    warden = Warden(client, ruleset)
    state = GameState(ruleset=ruleset.id, adventure=args.premise)
    state.party = build_party(ruleset, dice, name, args.companions)
    session = Session(state, warden, ruleset, dice)

    print(BOLD(CYAN(f"\n  ⚔  {ruleset.name} — run by an AI {ruleset.warden_title}")))
    print(DIM(f"     {ruleset.attribution}"))
    show_sheet(state)
    print(DIM("  commands: /sheet  /look  /quit   — anything else is what you do\n"))
    print(DIM("  (the Warden is setting the scene...)"))

    try:
        opening = session.begin(args.premise)
        print()
        print(wrap(MAG(opening.get("narration", ""))))
        if opening.get("options"):
            print()
            print(YELLOW("  You could: ") + DIM(" · ".join(opening["options"])))
    except LLMError as exc:
        print(RED(f"\nWarden error: {exc}"), file=sys.stderr)
        return 1

    # -- main loop ----------------------------------------------------------
    while True:
        try:
            raw = input(f"\n{BOLD(GREEN(name + ' > '))}").strip()
        except (EOFError, KeyboardInterrupt):
            print(DIM("\n  farewell.")); return 0
        if not raw:
            continue
        if raw in ("/quit", "/q", "/exit"):
            print(DIM("  farewell.")); return 0
        if raw == "/sheet":
            show_sheet(state); continue
        if raw == "/look":
            print(wrap(DIM(f"{state.scene.location} — {state.scene.description}")))
            if state.scene.exits:
                print(DIM("  exits: " + ", ".join(state.scene.exits)))
            continue

        try:
            print(DIM("  (the Warden considers...)"))
            result = session.take_turn(name, raw)
            print_turn(result)
            # AI companions act after the human.
            for mate in state.living_party():
                if mate.is_ai:
                    print(DIM(f"\n  ({mate.name} acts...)"))
                    out = session.ai_turn(mate)
                    say = out.get("ai_decision", {}).get("say")
                    if say:
                        print(CYAN(f'  {mate.name}: "{say}"'))
                    print_turn(out)
            if state.in_combat:
                show_sheet(state)
            if not state.living_party():
                print(RED("\n  The party has fallen. The Wood keeps its secrets.\n"))
                return 0
        except LLMError as exc:
            print(RED(f"  Warden error: {exc}"))
        except KeyboardInterrupt:
            print(DIM("\n  farewell.")); return 0


if __name__ == "__main__":
    raise SystemExit(main())
