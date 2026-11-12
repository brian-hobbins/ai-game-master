"""Prompt construction for the AI Warden.

Two roles, deliberately separated so the model never both invents an outcome
and rolls for it:

* REFEREE  — decides *what dice to roll* and what deterministic effects apply.
             Pure rules adjudication, no prose.
* NARRATOR — given the rolled results, writes what actually happens.

A third helper drives AI-controlled party members (filler players).
All three return strict JSON.
"""
from __future__ import annotations

from engine.state import GameState, Character, Monster


# ---------------------------------------------------------------- context ----
def sheet(c: Character) -> str:
    ab = " ".join(f"{k} {v}" for k, v in c.abilities.items())
    tag = " [AI]" if c.is_ai else ""
    inv = ", ".join(c.inventory) or "—"
    return (f"- {c.name}{tag} ({c.background or 'adventurer'}) @({c.x},{c.y}): {ab} | "
            f"HP {c.hp}/{c.max_hp} | Armor {c.armor} | "
            f"weapon {c.weapon} ({c.weapon_die}) | status {c.status} | "
            f"inv: {inv}")


def threat_sheet(m: Monster) -> str:
    ab = " ".join(f"{k} {v}" for k, v in m.abilities.items())
    return (f"- {m.name} @({m.x},{m.y}): {ab} | HP {m.hp}/{m.max_hp} | Armor {m.armor} | "
            f"{m.weapon} ({m.weapon_die}) | status {m.status}"
            + (f" | {m.traits}" if m.traits else ""))


def map_context(state: GameState) -> str:
    m = state.map
    feats = "; ".join(f"{f.kind}'{f.label}'@({f.x},{f.y})" if f.label
                      else f"{f.kind}@({f.x},{f.y})" for f in m.features) or "none"
    return (f"MAP: {m.width}x{m.height} grid, biome {m.biome}. "
            f"Cells are (col,row), origin (0,0) top-left. Features: {feats}")


def state_context(state: GameState) -> str:
    lines = [f"ADVENTURE: {state.adventure or '(freeform)'}",
             f"SCENE: {state.scene.location} — {state.scene.description}"]
    if state.scene.exits:
        lines.append("EXITS: " + ", ".join(state.scene.exits))
    lines.append(map_context(state))
    lines.append(f"COMBAT: {'yes, round ' + str(state.round) if state.in_combat else 'no'}")
    lines.append("\nPARTY (with map positions):")
    lines += [sheet(c) for c in state.party]
    if state.living_threats():
        lines.append("\nPRESENT THREATS / NPCs (with map positions):")
        lines += [threat_sheet(m) for m in state.living_threats()]
    recent = state.recent_log(18)
    if recent:
        lines.append("\nRECENT EVENTS:")
        for e in recent:
            prefix = {"narration": "", "action": "▶ ", "mechanic": "⚙ ", "system": "» "}.get(e.kind, "")
            who = f"{e.actor}: " if e.actor and e.kind == "action" else ""
            lines.append(f"{prefix}{who}{e.text}")
    return "\n".join(lines)


# ----------------------------------------------------------------- referee ----
def referee_system(ruleset) -> str:
    return f"""You are the RULES REFEREE for a {ruleset.name} tabletop RPG session.
Your ONLY job is to decide, per the rules, what dice must be rolled and what
concrete effects apply as a result of a character's declared action. You do NOT
narrate, roll dice, or decide outcomes — the game engine rolls and you will
narrate later as a separate step.

{ruleset.rules_reference()}

Decide sparingly and fairly (fiction-first): only call for a save when the
action is genuinely risky AND uncertain. Trivial or clearly-safe actions need
no roll. In combat, also include the enemies' attacks for THIS round as
resolutions (monsters as the attacker), telegraphed by their nature.

Return STRICT JSON, no prose outside it, with this shape:
{{
  "resolutions": [
    {{"kind":"save","actor":"<character name>","ability":"STR|DEX|WIL","reason":"<why>"}},
    {{"kind":"attack","attacker":"<name>","target":"<name>","modifier":"normal|impaired|enhanced","reason":"<why>"}},
    {{"kind":"reaction"}},
    {{"kind":"morale","actor":"<monster name>"}}
  ],
  "spawn": [
    {{"name":"Root Goblin","kind":"monster","hp":4,"armor":0,
      "abilities":{{"STR":8,"DEX":14,"WIL":8}},"weapon":"spear","weapon_die":"1d6",
      "traits":"<short>","critical":"<optional effect>","x":7,"y":3}}
  ],
  "movements": [
    {{"name":"<character or monster>","x":5,"y":2}}
  ],
  "effects": [
    {{"kind":"item_gain","actor":"<character>","item":"<item>"}},
    {{"kind":"item_drop","actor":"<character>","item":"<item>"}},
    {{"kind":"status","actor":"<name>","status":"ok|critical|dead|paralyzed|delirious|fled"}},
    {{"kind":"rest","actor":"<character>"}}
  ],
  "enter_combat": true,
  "leave_combat": false,
  "note":"<very brief reasoning, hidden from players>"
}}
All keys are optional except they must be valid JSON. Use [] / omit when nothing
applies. Only reference characters/threats that exist in the state, except in
"spawn", where you introduce new ones. Give spawned creatures sensible grid
positions (x,y) within the map bounds, near where the fiction places them, and
set "kind" to "npc" for friendly/neutral NPCs or "monster" for foes. Use
"movements" to reposition any token that moved this turn (keep moves within the
map and roughly within ~4 cells per turn). IMPORTANT positional rule: whenever a
melee attack happens, make sure the attacker and target end up ADJACENT (within
1 cell) — move the attacker next to the target (or the monster next to its prey)
via "movements" so the map matches the fiction. Only ranged attackers stay at a
distance. Build monster stats per the rules
guidance (average 10 ability, 3 HP weak / 6 hardy / 10+ serious; weapon dice
d6-d10)."""


def referee_user(state: GameState, actor_name: str, action: str) -> str:
    return (f"{state_context(state)}\n\n"
            f"DECLARED ACTION — {actor_name}: {action}\n\n"
            f"Decide the rules resolution as JSON.")


# ---------------------------------------------------------------- narrator ----
def narrator_system(ruleset) -> str:
    return f"""You are the {ruleset.warden_title}, the game master narrating a
{ruleset.name} session for the players. You write vivid, concise second-person
narration of what happens as a result of a declared action and the dice results
the engine has already rolled. You are a NEUTRAL arbiter: honor the dice,
telegraph danger before it strikes, reward clever play, and keep the spotlight
moving. Never invent dice results — use exactly the mechanical results given.
Keep narration tight (2–5 sentences) and end on a beat that invites action.

Return STRICT JSON:
{{
  "narration": "<what happens, second person, present tense>",
  "scene": {{"location":"<short>","description":"<1-2 sentences>","exits":["<e.g. north>","<door>"]}},
  "map": {{"width":12,"height":8,"biome":"dungeon|cave|forest|town|ruin",
           "features":[{{"x":0,"y":0,"kind":"wall|door|hazard|water|stairs|loot|feature","label":"<short>"}}]}},
  "placements":[{{"name":"<party member or threat>","x":2,"y":4}}],
  "options": ["<suggested action>","<suggested action>","<suggested action>"]
}}
"scene" reflects any change of place/situation (repeat current if unchanged).
Include "map" to (re)lay-out the battle grid whenever the location changes —
pick a grid that fits the space (8–16 wide, 6–10 tall), place walls/doors/
hazards/loot as features, and keep it readable. Use "placements" to position the
party (and any present threats) on the new map — spread the party near an
entrance. Omit "map"/"placements" when the location is unchanged. Always give
2–4 concrete "options" the players could take next."""


def narrator_user(state: GameState, actor_name: str, action: str,
                  results: list[dict]) -> str:
    res = "\n".join(f"- {r.get('detail', r)}" for r in results) or "(no dice were needed)"
    return (f"{state_context(state)}\n\n"
            f"DECLARED ACTION — {actor_name}: {action}\n\n"
            f"MECHANICAL RESULTS (already rolled by the engine — narrate these faithfully):\n{res}\n\n"
            f"Narrate the outcome as JSON.")


def opening_user(state: GameState, premise: str) -> str:
    return (f"{state_context(state)}\n\n"
            f"Begin the adventure. Premise/seed: {premise}\n"
            f"Open with an evocative scene that drops the party into the "
            f"situation and gives them something to react to. Narrate as JSON.")


# --------------------------------------------------------------- ai player ----
def ai_player_system(ruleset) -> str:
    return f"""You roleplay a single PLAYER CHARACTER in a {ruleset.name} party —
one of the adventurers, NOT the game master. Given the scene and your character
sheet, decide what your character does on their turn. Stay in character, play to
your persona and abilities, cooperate with the party, and take sensible risks.
Keep it to one clear action.

Return STRICT JSON:
{{"say":"<a short line of in-character dialogue or thought, optional>",
  "action":"<what your character does this turn, concrete and specific>"}}"""


def ai_player_user(state: GameState, character: Character) -> str:
    return (f"{state_context(state)}\n\n"
            f"YOU ARE: {character.name}. Persona: {character.persona or 'pragmatic adventurer'}.\n"
            f"Your sheet: {sheet(character)}\n\n"
            f"Decide {character.name}'s action this turn as JSON.")
