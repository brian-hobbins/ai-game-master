"""Game state: the authoritative record of the world.

These are plain, serializable dataclasses. The engine mutates them through the
ruleset; the AI Warden only ever *reads* a summary of them. Everything here is
ruleset-neutral on purpose — abilities are a dict keyed by whatever ability
names the active ruleset declares (Cairn: STR/DEX/WIL; D&D would add more),
so the same state model carries any system.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Character:
    """A player character or AI-controlled party member."""
    name: str
    abilities: dict[str, int]          # e.g. {"STR": 10, "DEX": 12, "WIL": 9}
    hp: int
    max_hp: int
    armor: int = 0
    inventory: list[str] = field(default_factory=list)
    gold: int = 0
    background: str = ""
    traits: str = ""
    weapon: str = "unarmed"
    weapon_die: str = "1d4"
    status: str = "ok"                 # ok | critical | paralyzed | delirious | dead
    is_ai: bool = False                # True = an AI fills this seat
    persona: str = ""                  # how an AI player should roleplay this PC
    notes: str = ""
    x: int = 0                         # token position on the battle map (cells)
    y: int = 0

    def alive(self) -> bool:
        return self.status != "dead"


@dataclass
class Monster:
    """An NPC or monster the Warden can bring into a scene."""
    name: str
    abilities: dict[str, int]
    hp: int
    max_hp: int
    armor: int = 0
    weapon: str = "claws"
    weapon_die: str = "1d6"
    traits: str = ""
    critical: str = ""                 # special effect when it deals critical damage
    status: str = "ok"                 # ok | critical | dead | fled
    kind: str = "monster"              # monster | npc (affects token color)
    x: int = 0
    y: int = 0

    def alive(self) -> bool:
        return self.status not in ("dead", "fled")


@dataclass
class Feature:
    """A fixed element on the battle map: wall, door, rubble, hazard, chest…"""
    x: int
    y: int
    kind: str = "feature"             # wall | door | hazard | water | stairs | loot | feature
    label: str = ""


@dataclass
class GameMap:
    width: int = 12
    height: int = 8
    biome: str = "dungeon"            # drives the floor styling (dungeon/forest/cave/town)
    features: list["Feature"] = field(default_factory=list)


@dataclass
class Scene:
    location: str = "Unknown"
    description: str = ""
    exits: list[str] = field(default_factory=list)


@dataclass
class Event:
    """One entry in the shared session log: narration, a mechanic, or a line
    of play. This log is both the transcript players read and the memory the
    Warden is given each turn."""
    kind: str                          # narration | mechanic | action | system
    text: str
    actor: str = ""


@dataclass
class GameState:
    ruleset: str
    adventure: str = ""
    scene: Scene = field(default_factory=Scene)
    map: GameMap = field(default_factory=GameMap)
    party: list[Character] = field(default_factory=list)
    threats: list[Monster] = field(default_factory=list)   # monsters/NPCs in play
    log: list[Event] = field(default_factory=list)
    in_combat: bool = False
    round: int = 0

    # -- helpers ------------------------------------------------------------
    def living_party(self) -> list[Character]:
        return [c for c in self.party if c.alive()]

    def living_threats(self) -> list[Monster]:
        return [m for m in self.threats if m.alive()]

    def find_character(self, name: str) -> Optional[Character]:
        return _find(self.party, name)

    def find_threat(self, name: str) -> Optional[Monster]:
        return _find(self.threats, name)

    def combatant(self, name: str):
        return self.find_character(name) or self.find_threat(name)

    def add_event(self, kind: str, text: str, actor: str = "") -> None:
        self.log.append(Event(kind=kind, text=text, actor=actor))

    def recent_log(self, n: int = 24) -> list[Event]:
        return self.log[-n:]

    def to_dict(self) -> dict:
        return asdict(self)


def _find(items, name: str):
    if not name:
        return None
    needle = name.strip().lower()
    # exact first, then prefix/substring (the LLM may abbreviate a name)
    for it in items:
        if it.name.lower() == needle:
            return it
    for it in items:
        if needle in it.name.lower() or it.name.lower() in needle:
            return it
    return None
