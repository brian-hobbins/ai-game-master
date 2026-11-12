"""The Ruleset interface — the seam that lets players swap game systems.

A ruleset owns every *mechanical* decision: how a character is built, how a
save or an attack resolves, what happens at 0 HP. The engine and the AI Warden
talk to this interface and nothing below it, so adding D&D 5e, OSRIC, Fate,
etc. later means writing one new subclass — no changes to the engine or the
Warden prompts.

Resolution results are returned as structured, *already-narratable* dicts and
the ruleset mutates target state in place (HP, ability loss, death). That
keeps dice and rules entirely out of the language model.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from engine.dice import Dice
from engine.state import Character, Monster


class Ruleset(ABC):
    # --- identity / licensing (shown in UI + attribution) ------------------
    id: str = "base"
    name: str = "Base Ruleset"
    version: str = "0"
    warden_title: str = "Game Master"       # Cairn calls it the "Warden"
    license: str = ""
    attribution: str = ""

    @property
    @abstractmethod
    def abilities(self) -> list[str]:
        """Ability score keys this system uses, e.g. ['STR','DEX','WIL']."""

    @abstractmethod
    def rules_reference(self) -> str:
        """A compact rules digest handed to the Warden as context each turn.
        Must be short enough to send every turn but complete enough to
        adjudicate fairly."""

    # --- prompt hints (optional; let a system tailor the referee schema) ----
    def save_prompt(self) -> str:
        """The enum shown for a save's `ability` field in the referee schema."""
        return "|".join(self.abilities)

    def monster_guidance(self) -> str:
        """One line telling the Warden how to stat a spawned creature."""
        return ("Build monster stats to fit this system: ability scores, HP, "
                "Armor and weapon dice consistent with the rules digest above.")

    # --- character / monster construction ----------------------------------
    @abstractmethod
    def create_character(self, dice: Dice, name: str, background: str = "",
                         traits: str = "", is_ai: bool = False,
                         persona: str = "") -> Character:
        ...

    @abstractmethod
    def make_monster(self, dice: Dice, spec: dict) -> Monster:
        """Build a Monster from a loose spec the Warden proposes
        (name, hp, abilities, weapon, etc.), filling sane defaults."""

    # --- resolution (the engine calls these; each mutates state) -----------
    @abstractmethod
    def roll_save(self, dice: Dice, actor, ability: str, reason: str = "",
                  dc: int | None = None) -> dict:
        """Resolve a save. `dc` is used by systems that roll against a target
        number (D&D); systems that compare to an ability score (Cairn) ignore it."""
        ...

    @abstractmethod
    def resolve_attack(self, dice: Dice, attacker, target, *,
                       weapon_die: str | None = None, modifier: str = "normal",
                       reason: str = "") -> dict:
        """Resolve one attack and apply damage/critical/death to `target`."""

    @abstractmethod
    def reaction_roll(self, dice: Dice) -> dict:
        ...

    @abstractmethod
    def morale_check(self, dice: Dice, creature) -> dict:
        ...

    def short_rest(self, actor: Character) -> dict:
        """Default: a breather restores HP to max (Cairn-style). Systems that
        heal differently override this."""
        before = actor.hp
        actor.hp = actor.max_hp
        return {"kind": "rest", "actor": actor.name,
                "restored": actor.max_hp - before, "hp": actor.hp}
