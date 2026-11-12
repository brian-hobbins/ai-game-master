"""Dungeons & Dragons 3.5 ruleset (d20 System, OGL).

Implements the core 3.5 resolution loop: six abilities (4d6-drop-lowest),
ability modifiers = (score − 10) ÷ 2, d20 + bonuses rolled HIGH, attacks vs
Armor Class, three saving throws (Fortitude / Reflex / Will) vs a DC, criticals
on a natural 20 (confirmed), and the −10 HP death threshold.

This content is derived from the System Reference Document v3.5, released by
Wizards of the Coast under the Open Game License v1.0a. Open Game Content — see
NOTICE.md and OGL-v1.0a.md. "Dungeons & Dragons" and "D&D" are trademarks of
Wizards of the Coast and are NOT part of the OGC; this system is labelled
"d20 3.5 (SRD)" in the UI for that reason.
"""
from __future__ import annotations

from engine.dice import Dice
from engine.state import Character, Monster
from rulesets.base import Ruleset

ABILITIES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]


def _mod(score: int) -> int:
    """3.5 ability modifier."""
    return (int(score) - 10) // 2


def _fmt(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


# Light level-1 class kit: hit die, base attack bonus, good saves, starting
# armor (AC bonus from armor+shield), signature weapon, attack ability, and the
# order abilities are assigned (best roll first). Classless flavor like
# "warrior"/"mage" maps onto the nearest class.
_CLASSES = {
    "fighter":   dict(hd=10, bab=1, good={"fort"},            armor=6, weapon="longsword",     wdie="1d8",  atk="STR", mode="melee",  prio=["STR","CON","DEX","WIS","CHA","INT"]),
    "barbarian": dict(hd=12, bab=1, good={"fort"},            armor=3, weapon="greataxe",      wdie="1d12", atk="STR", mode="melee",  prio=["STR","CON","DEX","WIS","CHA","INT"]),
    "paladin":   dict(hd=10, bab=1, good={"fort"},            armor=7, weapon="longsword",     wdie="1d8",  atk="STR", mode="melee",  prio=["STR","CHA","CON","WIS","DEX","INT"]),
    "ranger":    dict(hd=8,  bab=1, good={"fort","ref"},      armor=3, weapon="longbow",       wdie="1d8",  atk="DEX", mode="ranged", prio=["DEX","WIS","CON","STR","INT","CHA"]),
    "rogue":     dict(hd=6,  bab=0, good={"ref"},             armor=2, weapon="short sword",   wdie="1d6",  atk="DEX", mode="melee",  prio=["DEX","INT","CON","WIS","CHA","STR"]),
    "cleric":    dict(hd=8,  bab=0, good={"fort","will"},     armor=6, weapon="heavy mace",    wdie="1d8",  atk="STR", mode="melee",  prio=["WIS","STR","CON","CHA","DEX","INT"], caster="divine"),
    "druid":     dict(hd=8,  bab=0, good={"fort","will"},     armor=2, weapon="scimitar",      wdie="1d6",  atk="STR", mode="melee",  prio=["WIS","CON","DEX","STR","CHA","INT"], caster="divine"),
    "wizard":    dict(hd=4,  bab=0, good={"will"},            armor=0, weapon="quarterstaff",  wdie="1d6",  atk="STR", mode="melee",  prio=["INT","CON","DEX","WIS","CHA","STR"], caster="arcane"),
    "sorcerer":  dict(hd=4,  bab=0, good={"will"},            armor=0, weapon="dagger",        wdie="1d4",  atk="DEX", mode="ranged", prio=["CHA","CON","DEX","WIS","INT","STR"], caster="arcane"),
    "bard":      dict(hd=6,  bab=0, good={"ref","will"},      armor=2, weapon="rapier",        wdie="1d6",  atk="DEX", mode="melee",  prio=["CHA","DEX","CON","INT","WIS","STR"], caster="arcane"),
    "monk":      dict(hd=8,  bab=0, good={"fort","ref","will"},armor=0, weapon="unarmed strike",wdie="1d6", atk="DEX", mode="melee",  prio=["DEX","WIS","CON","STR","INT","CHA"]),
}

# Flavor words → class
_CLASS_ALIASES = {
    "warrior": "fighter", "soldier": "fighter", "knight": "fighter", "mercenary": "fighter",
    "sellsword": "fighter", "guard": "fighter",
    "mage": "wizard", "wizard": "wizard", "magician": "wizard", "arcanist": "wizard",
    "sorcerer": "sorcerer", "warlock": "sorcerer",
    "priest": "cleric", "cleric": "cleric", "healer": "cleric", "acolyte": "cleric",
    "druid": "druid", "shaman": "druid",
    "thief": "rogue", "rogue": "rogue", "scout": "rogue", "assassin": "rogue", "burglar": "rogue",
    "archer": "ranger", "ranger": "ranger", "hunter": "ranger", "tracker": "ranger",
    "barbarian": "barbarian", "berserker": "barbarian", "brute": "barbarian",
    "bard": "bard", "minstrel": "bard", "skald": "bard",
    "monk": "monk", "martial artist": "monk",
    "paladin": "paladin", "crusader": "paladin",
}


def _infer_class(text: str) -> str:
    t = (text or "").lower()
    for word, cls in _CLASS_ALIASES.items():
        if word in t:
            return cls
    for cls in _CLASSES:                 # direct class name mentioned
        if cls in t:
            return cls
    return "fighter"


class DnD35Ruleset(Ruleset):
    id = "dnd35"
    name = "d20 3.5 (SRD)"
    version = "3.5"
    warden_title = "Dungeon Master"
    license = "OGL v1.0a"
    attribution = ("Rules derived from the System Reference Document v3.5, "
                   "© Wizards of the Coast, used under the Open Game License v1.0a. "
                   "See NOTICE.md and OGL-v1.0a.md.")

    @property
    def abilities(self) -> list[str]:
        return ABILITIES

    def rules_reference(self) -> str:
        return _RULES_DIGEST

    def save_prompt(self) -> str:
        return "Fort|Ref|Will"

    def monster_guidance(self) -> str:
        return ("Stat creatures as D&D 3.5 monsters: give 'armor' as the Armor "
                "Class (AC, typically 10-20), 'hp' (a CR-1 minion ~5-11, a tough "
                "foe ~15-30), 'attack_bonus' (a whole number, e.g. +3), "
                "'weapon_die' for its attack (1d4-2d6), and optionally "
                "'saves':{\"fort\":n,\"ref\":n,\"will\":n}. Ability scores default "
                "to 10-14. Set 'critical' for any special effect.")

    # -- character creation -------------------------------------------------
    def create_character(self, dice, name, background="", traits="",
                         is_ai=False, persona="") -> Character:
        cls = _infer_class(f"{persona} {traits} {background}")
        spec = _CLASSES[cls]
        # 4d6 drop lowest, six times, then arrange best-first into class priority.
        rolls = sorted((self._four_d6(dice) for _ in range(6)), reverse=True)
        scores = {ab: rolls[i] for i, ab in enumerate(spec["prio"])}
        con_mod = _mod(scores["CON"])
        hp = max(1, spec["hd"] + con_mod)        # max hit die at level 1
        ac = 10 + spec["armor"] + _mod(scores["DEX"])
        bab = spec["bab"]
        atk_ability = spec["atk"]
        attack_bonus = bab + _mod(scores[atk_ability])
        extras = {
            "cls": cls, "level": 1, "bab": bab, "hd": spec["hd"],
            "attack_bonus": attack_bonus, "attack_mode": spec["mode"],
            "attack_ability": atk_ability,
            "save_base": {s: (2 if s in spec["good"] else 0)
                          for s in ("fort", "ref", "will")},
            "caster": spec.get("caster", ""),
        }
        inv = ["explorer's kit", "torch", "50 ft rope", spec["weapon"]]
        if spec["armor"] >= 4:
            inv.append("heavy armor")
        elif spec["armor"] >= 2:
            inv.append("light armor")
        if spec["armor"] in (6, 7, 4):
            inv.append("shield")
        if spec.get("caster") == "arcane":
            inv.append("spellbook" if cls == "wizard" else "component pouch")
        elif spec.get("caster") == "divine":
            inv.append("holy symbol")
        return Character(
            name=name, abilities=scores, hp=hp, max_hp=hp, armor=ac,
            inventory=inv, gold=dice.roll("4d4").total * 10,
            background=background or f"{cls.title()} 1",
            traits=traits, weapon=spec["weapon"], weapon_die=spec["wdie"],
            is_ai=is_ai, persona=persona, extras=extras,
        )

    @staticmethod
    def _four_d6(dice) -> int:
        r = dice.roll("4d6")
        return sum(sorted(r.rolls)[1:])          # drop the lowest of four

    def make_monster(self, dice, spec: dict) -> Monster:
        ab = spec.get("abilities") or {}
        abilities = {a: int(ab.get(a, 10 + (2 if a in ("STR", "CON") else 0)))
                     for a in ABILITIES}
        hp = int(spec.get("hp") or dice.roll("2d8").total)
        ac = int(spec.get("ac", spec.get("armor", 13)))
        saves = spec.get("saves") or {}
        extras = {
            "attack_bonus": int(spec.get("attack_bonus", 1 + _mod(abilities["STR"]))),
            "attack_mode": spec.get("attack_mode", "melee"),
            "save_base": {s: int(saves.get(s, 1)) for s in ("fort", "ref", "will")},
        }
        return Monster(
            name=spec.get("name", "Creature"), abilities=abilities,
            hp=hp, max_hp=hp, armor=ac,
            weapon=spec.get("weapon", "claws"),
            weapon_die=spec.get("weapon_die", "1d6"),
            traits=spec.get("traits", ""), critical=spec.get("critical", ""),
            kind=spec.get("kind", "monster"),
            x=int(spec.get("x", 0)), y=int(spec.get("y", 0)), extras=extras,
        )

    # -- resolution ---------------------------------------------------------
    _SAVE_MAP = {
        "FORT": ("fort", "CON"), "FORTITUDE": ("fort", "CON"),
        "CON": ("fort", "CON"), "STR": ("fort", "CON"),
        "REF": ("ref", "DEX"), "REFLEX": ("ref", "DEX"), "DEX": ("ref", "DEX"),
        "WILL": ("will", "WIS"), "WIL": ("will", "WIS"), "WIS": ("will", "WIS"),
        "INT": ("will", "WIS"), "CHA": ("will", "WIS"),
    }

    def roll_save(self, dice, actor, ability, reason="", dc=None) -> dict:
        cat, key = self._SAVE_MAP.get((ability or "WILL").upper(), ("will", "WIS"))
        base = (getattr(actor, "extras", {}) or {}).get("save_base", {}).get(cat, 0)
        bonus = base + _mod(actor.abilities.get(key, 10))
        dc = int(dc) if dc not in (None, "") else 15
        r = dice.d20()
        nat = r.total
        total = nat + bonus
        # 3.5: natural 1 always fails, natural 20 always succeeds.
        if nat == 1:
            success = False
        elif nat == 20:
            success = True
        else:
            success = total >= dc
        return {
            "kind": "save", "actor": actor.name, "ability": cat.title(),
            "reason": reason, "roll": nat, "bonus": bonus, "dc": dc,
            "total": total, "success": success,
            "detail": f"{actor.name} {cat.title()} save: d20 {nat} {_fmt(bonus)} "
                      f"= {total} vs DC {dc} — {'SUCCESS' if success else 'FAILURE'}",
        }

    def resolve_attack(self, dice, attacker, target, *, weapon_die=None,
                       modifier="normal", reason="") -> dict:
        die = weapon_die or getattr(attacker, "weapon_die", "1d4") or "1d4"
        ax = getattr(attacker, "extras", {}) or {}
        atk_bonus = int(ax.get("attack_bonus", 0))
        situational = {"enhanced": 2, "impaired": -2}.get(modifier, 0)  # flank/charge vs cover/prone
        ac = getattr(target, "armor", 10) or 10
        weapon = getattr(attacker, "weapon", "attack")

        r = dice.d20()
        nat = r.total
        total = nat + atk_bonus + situational
        auto_miss = (nat == 1)
        auto_hit = (nat == 20)
        hit = auto_hit or (not auto_miss and total >= ac)

        if not hit:
            return {
                "kind": "attack", "attacker": attacker.name, "target": target.name,
                "weapon": weapon, "modifier": modifier, "reason": reason,
                "roll": nat, "attack_total": total, "ac": ac, "hit": False, "damage": 0,
                "detail": f"{attacker.name} attacks {target.name} with {weapon}: "
                          f"d20 {nat} {_fmt(atk_bonus + situational)} = {total} vs AC {ac} — MISS",
            }

        # damage: weapon die + STR mod on melee (not on ranged)
        dmg_mod = 0
        if ax.get("attack_mode", "melee") == "melee":
            dmg_mod = _mod(attacker.abilities.get("STR", 10))
        dmg_roll = dice.roll(die).total
        # critical: natural 20, confirmed by a second attack roll that also hits.
        crit = False
        if auto_hit:
            confirm = dice.d20().total + atk_bonus + situational
            crit = confirm >= ac
        base_dmg = dmg_roll + dmg_mod
        dmg = max(1, base_dmg * 2 if crit else base_dmg)   # ×2 critical
        effects = self._apply_damage(dice, target, dmg)

        label = "CRITICAL HIT" if crit else ("HIT (nat 20)" if auto_hit else "HIT")
        detail = (f"{attacker.name} hits {target.name} with {weapon}: "
                  f"d20 {nat} {_fmt(atk_bonus + situational)} = {total} vs AC {ac} — {label}; "
                  f"{die}{_fmt(dmg_mod) if dmg_mod else ''}"
                  f"{' ×2' if crit else ''} = {dmg} damage")
        if effects.get("consequence"):
            detail += f"  → {effects['consequence']}"
        return {
            "kind": "attack", "attacker": attacker.name, "target": target.name,
            "weapon": weapon, "modifier": modifier, "reason": reason,
            "roll": nat, "attack_total": total, "ac": ac, "hit": True,
            "critical": crit, "damage": dmg, "detail": detail, **effects,
        }

    def _apply_damage(self, dice, target, dmg: int) -> dict:
        """3.5 HP track: 0 HP = disabled, below 0 = dying/unconscious,
        −10 or lower = dead."""
        before = target.hp
        target.hp -= dmg
        out = {"hp_before": before, "hp_after": target.hp, "dealt": dmg}
        parts = []
        if target.hp <= -10:
            target.status = "dead"
            out["died"] = True
            parts.append(f"dropped to {target.hp} HP (−10 or lower) — SLAIN")
        elif target.hp < 0:
            target.status = "critical"
            out["critical"] = True
            parts.append(f"at {target.hp} HP — dying & unconscious (stabilize or lose 1/round)")
        elif target.hp == 0:
            target.status = "critical"
            out["disabled"] = True
            parts.append("at 0 HP — disabled (only a single move or standard action)")
        out["consequence"] = "; ".join(parts)
        return out

    def reaction_roll(self, dice) -> dict:
        # NPC starting attitude (3.5 Diplomacy table, GM aid): roll 2d6.
        r = dice.roll("2d6").total
        table = [(2, "Hostile"), (4, "Unfriendly"), (9, "Indifferent"),
                 (11, "Friendly"), (12, "Helpful")]
        mood = next(label for ceil, label in table if r <= ceil)
        return {"kind": "reaction", "roll": r, "mood": mood,
                "detail": f"NPC attitude (2d6 {r}): {mood}"}

    def morale_check(self, dice, creature) -> dict:
        # 3.5 has no core morale rule; this is the common optional Will save.
        save = self.roll_save(dice, creature, "Will", "morale", dc=15)
        if not save["success"]:
            creature.status = "fled"
        return {"kind": "morale", "actor": creature.name,
                "fled": not save["success"], "save": save,
                "detail": f"{creature.name} morale ({'holds' if save['success'] else 'FLEES'})"}

    def short_rest(self, actor) -> dict:
        # A breather + quick aid: heal level + CON mod (3.5 heals slowly).
        ex = getattr(actor, "extras", {}) or {}
        heal = max(1, ex.get("level", 1) + _mod(actor.abilities.get("CON", 10)))
        before = actor.hp
        actor.hp = min(actor.max_hp, actor.hp + heal)
        return {"kind": "rest", "actor": actor.name,
                "restored": actor.hp - before, "hp": actor.hp}


# Compact, send-every-turn digest derived from the SRD v3.5 (OGL v1.0a, WotC).
_RULES_DIGEST = """\
D&D 3.5 (d20 System) — RULES DIGEST (SRD v3.5, OGL v1.0a)

ABILITIES: STR, DEX, CON, INT, WIS, CHA. Modifier = (score − 10) ÷ 2, rounded
down (10-11 = +0, 14 = +2, 8 = −1, 18 = +4). The engine applies modifiers; you
only decide which rolls happen.

CORE MECHANIC: roll d20, add the relevant bonus, compare to a target number;
HIGHER is better. Meet or beat the number to succeed.

CHECKS & SAVES: For a risky, uncertain action, call a saving throw against a
Difficulty Class (DC). Pick the save and set the DC in the resolution:
  - Fortitude (poison, disease, raw physical shock) — CON-based.
  - Reflex (dodging area effects, traps, dragon breath) — DEX-based.
  - Will (fear, charm, illusion, mental force) — WIS-based.
Typical DC: 10 easy, 15 tough, 20 formidable, 25 near-impossible. Natural 1 on a
save always fails; natural 20 always succeeds. For a non-save test (climb, pick a
lock, sneak), a Reflex/DEX or Will/WIS save at an appropriate DC is a fine proxy.

COMBAT (per round):
  - Attack: the engine rolls d20 + attack bonus vs the target's Armor Class (AC).
    Give the ATTACK as a resolution; the engine computes the bonus from stats.
    Use modifier "enhanced" for a clear edge (flanking, charge, prone target),
    "impaired" for cover/concealment/attacking blind.
  - On a hit, the engine rolls weapon damage + STR mod (melee). Natural 20 is a
    threat and is auto-confirmed by the engine for a ×2 critical.
  - Initiative is abstracted: telegraph what foes do, then include their attacks
    for THIS round as resolutions with the monster as the attacker.
  - AC comes from armor + Dex + shield; the engine tracks it as the Armor value.

HIT POINTS & DEATH: damage reduces HP. 0 HP = disabled (one action/round).
Below 0 = dying and unconscious (lose 1 HP/round unless stabilized). −10 HP or
lower = dead. Healing and a night's rest restore HP; a short breather restores a
little.

MONSTERS: defined by AC, HP, attack bonus, damage die, and Fort/Ref/Will saves.
Build them to challenge the party's level; telegraph their nature.

MAGIC: casters prepare/know spells by class; casting a spell is an action. Adjudicate
spells by their fiction and, when they allow a save, set the save + DC
(DC 10 + spell level + casting-ability mod is a reasonable default).

PRINCIPLES: be a fair, consistent arbiter. Ask for a roll only when failure is
possible and interesting. Telegraph danger. Reward smart, specific play. "Dungeons
& Dragons" is a WotC trademark and is not used in play text — this is the SRD."""
