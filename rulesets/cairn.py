"""Cairn ruleset (First Edition).

Implements Cairn's mechanics faithfully: three abilities rolled 3d6, 1d6 Hit
Protection, roll-UNDER d20 saves, armor subtracted from weapon-die damage, and
the signature critical-damage / ability-loss death spiral.

Cairn is by Yochai Gal and is licensed CC BY-SA 4.0. See NOTICE.md. The rules
digest below is derived from the Cairn SRD and is therefore also CC BY-SA 4.0.
"""
from __future__ import annotations

import os

from engine.dice import Dice
from engine.state import Character, Monster
from rulesets.base import Ruleset

_HERE = os.path.dirname(os.path.abspath(__file__))

# Light starting-kit tables (abbreviated from the SRD gear tables) so a PC
# starts playable without the player having to roll on every table.
_WEAPONS = [
    ("dagger", "1d6"), ("cudgel", "1d6"), ("staff", "1d6"),
    ("sword", "1d8"), ("mace", "1d8"), ("axe", "1d8"),
    ("spear", "1d6"), ("bow", "1d6"), ("halberd", "1d10"),
]
_ARMOR = [("no armor", 0), ("leather armor", 1), ("mail armor", 2)]


class CairnRuleset(Ruleset):
    id = "cairn"
    name = "Cairn"
    version = "1.0"
    warden_title = "Warden"
    license = "CC BY-SA 4.0"
    attribution = "Cairn by Yochai Gal (cairnrpg.com), CC BY-SA 4.0."

    @property
    def abilities(self) -> list[str]:
        return ["STR", "DEX", "WIL"]

    def rules_reference(self) -> str:
        return _RULES_DIGEST

    def monster_guidance(self) -> str:
        return ("Build monster stats per Cairn norms (average 10 ability, "
                "3 HP weak / 6 hardy / 10+ serious; weapon dice d6-d10; "
                "Armor 0-3). Give 'armor' as the Armor value.")

    # -- character creation -------------------------------------------------
    def create_character(self, dice, name, background="", traits="",
                         is_ai=False, persona="") -> Character:
        # 3d6 in order, then the player may swap two — we keep the straight
        # roll for an auto-generated PC (the UI can offer swaps later).
        abilities = {a: dice.roll("3d6").total for a in self.abilities}
        hp = dice.d(6).total
        weapon, wdie = _WEAPONS[dice.d(len(_WEAPONS)).total - 1]
        armor_name, armor_val = _ARMOR[dice.d(3).total - 1]
        gold = dice.roll("3d6").total
        inv = ["three days' rations", "torch", weapon]
        if armor_val:
            inv.append(armor_name)
        return Character(
            name=name, abilities=abilities, hp=hp, max_hp=hp,
            armor=min(armor_val, 3), inventory=inv, gold=gold,
            background=background, traits=traits,
            weapon=weapon, weapon_die=wdie,
            is_ai=is_ai, persona=persona,
        )

    def make_monster(self, dice, spec: dict) -> Monster:
        ab = spec.get("abilities") or {}
        abilities = {a: int(ab.get(a, 10)) for a in self.abilities}
        hp = int(spec.get("hp") or dice.d(6).total)
        return Monster(
            name=spec.get("name", "Creature"),
            abilities=abilities,
            hp=hp, max_hp=hp,
            armor=min(int(spec.get("armor", 0)), 3),
            weapon=spec.get("weapon", "claws"),
            weapon_die=spec.get("weapon_die", "1d6"),
            traits=spec.get("traits", ""),
            critical=spec.get("critical", ""),
            kind=spec.get("kind", "monster"),
            x=int(spec.get("x", 0)), y=int(spec.get("y", 0)),
        )

    # -- resolution ---------------------------------------------------------
    def roll_save(self, dice, actor, ability, reason="", dc=None) -> dict:
        ability = ability.upper()
        score = actor.abilities.get(ability, 10)
        r = dice.d20()
        nat = r.total
        # 1 always succeeds, 20 always fails; otherwise roll-under.
        if nat == 1:
            success = True
        elif nat == 20:
            success = False
        else:
            success = nat <= score
        return {
            "kind": "save", "actor": actor.name, "ability": ability,
            "reason": reason, "roll": nat, "target": score, "success": success,
            "detail": f"{actor.name} rolls {nat} vs {ability} {score} — "
                      f"{'PASS' if success else 'FAIL'}",
        }

    def resolve_attack(self, dice, attacker, target, *, weapon_die=None,
                       modifier="normal", reason="") -> dict:
        die = weapon_die or getattr(attacker, "weapon_die", "1d4") or "1d4"
        # Cairn attack modifiers change the die, not a bonus.
        if modifier == "impaired":
            roll = dice.roll("1d4")
        elif modifier == "enhanced":
            roll = dice.roll("1d12")
        else:
            roll = dice.roll(die)
        raw = roll.total
        armor = getattr(target, "armor", 0)
        dmg = max(0, raw - armor)
        effects = self._apply_damage(dice, target, dmg)
        weapon = getattr(attacker, "weapon", "attack")
        detail = (f"{attacker.name} hits {target.name} with {weapon}: "
                  f"rolled {raw} − {armor} armor = {dmg} damage")
        if effects.get("consequence"):
            detail += f"  → {effects['consequence']}"
        return {
            "kind": "attack", "attacker": attacker.name, "target": target.name,
            "weapon": weapon, "modifier": modifier, "reason": reason,
            "roll": raw, "armor": armor, "damage": dmg,
            "detail": detail,
            **effects,
        }

    def _apply_damage(self, dice, target, dmg: int) -> dict:
        """Cairn damage pipeline: HP first, overflow to STR, then a STR save
        to avoid critical damage; STR 0 = death. HP exactly 0 = a Scar. Builds
        a human-readable `consequence` so the death spiral is visible in play."""
        hp_before = target.hp
        out = {"hp_before": hp_before}
        parts: list[str] = []
        target.hp -= dmg
        if target.hp < 0:
            overflow = -target.hp
            target.hp = 0
            str_before = target.abilities.get("STR", 0)
            target.abilities["STR"] = max(0, str_before - overflow)
            loss = str_before - target.abilities["STR"]
            out["str_loss"] = loss
            parts.append(f"{loss} STR lost (STR {str_before}→{target.abilities['STR']})")
            if target.abilities["STR"] <= 0:
                target.status = "dead"
                out["died"] = True
                parts.append("STR reduced to 0 — SLAIN")
            else:
                save = self.roll_save(dice, target, "STR", "critical damage")
                out["critical_save"] = save
                parts.append(save["detail"])
                if not save["success"]:
                    target.status = "critical"
                    out["critical"] = True
                    parts.append("CRITICAL DAMAGE — out of the fight, dying within the hour unless aided")
        elif target.hp == 0 and dmg > 0:
            out["scar"] = True
            parts.append("struck to exactly 0 HP — a lasting Scar")
        out["hp_after"] = target.hp
        out["dealt"] = dmg
        out["consequence"] = "; ".join(parts)
        return out

    def reaction_roll(self, dice) -> dict:
        r = dice.roll("2d6").total
        table = [(2, "Hostile"), (5, "Wary"), (8, "Curious"), (11, "Kind"), (12, "Helpful")]
        mood = next(label for ceil, label in table if r <= ceil)
        return {"kind": "reaction", "roll": r, "mood": mood,
                "detail": f"Reaction roll {r}: {mood}"}

    def morale_check(self, dice, creature) -> dict:
        save = self.roll_save(dice, creature, "WIL", "morale")
        if not save["success"]:
            creature.status = "fled"
        return {"kind": "morale", "actor": creature.name,
                "fled": not save["success"], "save": save,
                "detail": f"{creature.name} morale ({'holds' if save['success'] else 'FLEES'})"}


# Compact, send-every-turn rules digest derived from the Cairn SRD (CC BY-SA 4.0).
_RULES_DIGEST = """\
CAIRN — RULES DIGEST (CC BY-SA 4.0, Yochai Gal)

ABILITIES: STR (brawn/resistance), DEX (speed/stealth/reflexes), WIL
(persuasion/intimidation/magic). Scores ~3 deficient, 10 average, 18 legendary.

SAVES: To avoid a bad outcome from a risky choice, roll d20 and compare to the
relevant ability. Roll EQUAL or UNDER = pass. Natural 1 always passes; natural
20 always fails. Only call for a save when the action is genuinely risky and
the outcome is uncertain — Cairn is fiction-first; many actions just succeed.

HIT PROTECTION (HP): not health — it's luck/stamina to avoid real harm. Lost in
combat, fully restored by a short rest in safety.

COMBAT:
- Attacks HIT automatically; you roll the weapon's damage die, subtract the
  target's Armor (max 3), and deal the rest to HP. Unarmed = 1d4.
- Impaired attack (bad position) = roll 1d4 instead. Enhanced attack (helpless
  foe / daring maneuver) = roll 1d12 instead.
- Multiple attackers on one foe, or dual weapons: roll all, keep the highest.
- Initiative: at the start of combat each PC makes a DEX save to act before the
  enemies. Telegraph what monsters will likely do before dice are rolled.

CRITICAL DAMAGE & DEATH:
- Damage beyond 0 HP reduces STR by the remainder; then a STR save to avoid
  critical damage. Fail = out of action, dying within the hour unless helped.
- STR 0 = dead. DEX 0 = paralyzed. WIL 0 = delirious.
- Damage that lands a PC exactly at 0 HP leaves a lasting Scar.

MORALE: Enemies make a WIL save to avoid fleeing when they take their first
casualty and when they lose half their number; lone foes save at 0 HP. PCs are
never forced by morale.

REACTIONS (for unclear NPC attitude): 2d6 → 2 Hostile, 3-5 Wary, 6-8 Curious,
9-11 Kind, 12 Helpful.

MAGIC: Spellbooks hold one spell; casting adds a Fatigue (fills an inventory
slot). In danger/deprived, a WIL save may be required to avoid ill effects.

PRINCIPLES: Be a neutral arbiter. Telegraph danger — death is never random or
without warning. Reward clever, specific player thinking; let the fiction, not
the dice, drive most outcomes."""
