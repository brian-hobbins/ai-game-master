"""Deterministic tests for the dice, Cairn rules, and session orchestration.
No network / LLM calls — the engine is fully testable on its own, which is the
payoff of keeping rules and dice out of the model.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.dice import Dice, Roll
from engine.state import Character, GameState, Monster
from engine.session import Session
from rulesets import available, load_ruleset
from rulesets.cairn import CairnRuleset
from rulesets.dnd35 import DnD35Ruleset, _mod


class ScriptedDice(Dice):
    """Dice whose every roll() returns the next preset total (for exact cases)."""
    def __init__(self, totals):
        super().__init__()
        self._totals = list(totals)

    def roll(self, expr):
        v = self._totals.pop(0)
        return Roll(expr=str(expr), rolls=[v], modifier=0, total=v)


class TestDice(unittest.TestCase):
    def test_parsing_and_range(self):
        d = Dice(seed=1)
        for _ in range(200):
            self.assertTrue(1 <= d.roll("3d6").total <= 18)
            self.assertTrue(1 <= d.d20().total <= 20)

    def test_modifier(self):
        r = Dice(seed=1).roll("2d6+3")
        self.assertEqual(r.total, sum(r.rolls) + 3)
        self.assertEqual(r.modifier, 3)

    def test_seed_reproducible(self):
        a = [Dice(seed=42).roll("1d20").total for _ in range(5)]
        b = [Dice(seed=42).roll("1d20").total for _ in range(5)]
        self.assertEqual(a, b)

    def test_bad_expr(self):
        with self.assertRaises(ValueError):
            Dice().roll("banana")

    def test_highest_of(self):
        # keep the single highest of several dice (Cairn multi-attacker rule)
        best = Dice(seed=3).highest_of(["1d6", "1d6", "1d6"])
        self.assertTrue(1 <= best.total <= 6)


class TestCairnRules(unittest.TestCase):
    def setUp(self):
        self.rs = CairnRuleset()

    def test_character_creation(self):
        c = self.rs.create_character(Dice(seed=7), "Bea")
        self.assertEqual(set(c.abilities), {"STR", "DEX", "WIL"})
        for v in c.abilities.values():
            self.assertTrue(3 <= v <= 18)
        self.assertTrue(1 <= c.hp <= 6 and c.hp == c.max_hp)
        self.assertTrue(0 <= c.armor <= 3)
        self.assertIn("torch", c.inventory)

    def test_save_roll_under(self):
        c = Character("Bea", {"STR": 10, "DEX": 12, "WIL": 9}, hp=5, max_hp=5)
        self.assertTrue(self.rs.roll_save(ScriptedDice([5]), c, "STR")["success"])
        self.assertFalse(self.rs.roll_save(ScriptedDice([15]), c, "STR")["success"])
        # nat 1 always passes even vs low score; nat 20 always fails even vs high
        low = Character("x", {"STR": 3}, 1, 1)
        self.assertTrue(self.rs.roll_save(ScriptedDice([1]), low, "STR")["success"])
        high = Character("y", {"STR": 18}, 1, 1)
        self.assertFalse(self.rs.roll_save(ScriptedDice([20]), high, "STR")["success"])

    def test_attack_armor_subtraction(self):
        atk = Character("Bea", {"STR": 10}, 5, 5, weapon="sword", weapon_die="1d8")
        tgt = Monster("Goblin", {"STR": 8}, hp=5, max_hp=5, armor=1)
        res = self.rs.resolve_attack(ScriptedDice([4]), atk, tgt)  # 4 - 1 armor = 3
        self.assertEqual(res["damage"], 3)
        self.assertEqual(tgt.hp, 2)

    def test_critical_and_death(self):
        atk = Character("Bea", {"STR": 10}, 5, 5, weapon="axe", weapon_die="1d8")
        # overflow burns STR, then a STR save; scripted: weapon 8, then STR save 20 (fail)
        tgt = Monster("Thug", {"STR": 6}, hp=2, max_hp=2, armor=0)
        res = self.rs.resolve_attack(ScriptedDice([8, 20]), atk, tgt)
        self.assertEqual(tgt.hp, 0)
        self.assertEqual(res["str_loss"], 6)        # 8 dmg - 2 hp = 6 overflow
        self.assertEqual(tgt.status, "dead")        # STR 6 -> 0
        self.assertTrue(res.get("died"))

    def test_critical_survived(self):
        atk = Character("Bea", {"STR": 10}, 5, 5, weapon_die="1d6")
        tgt = Monster("Ogre", {"STR": 14}, hp=3, max_hp=3, armor=0)
        # 6 dmg -> hp 3-6=-3 overflow 3 -> STR 11; STR save rolls 2 (<=11) pass
        res = self.rs.resolve_attack(ScriptedDice([6, 2]), atk, tgt)
        self.assertEqual(tgt.status, "ok")
        self.assertFalse(res.get("died"))

    def test_reaction_table(self):
        self.assertEqual(self.rs.reaction_roll(ScriptedDice([2]))["mood"], "Hostile")
        self.assertEqual(self.rs.reaction_roll(ScriptedDice([7]))["mood"], "Curious")
        self.assertEqual(self.rs.reaction_roll(ScriptedDice([12]))["mood"], "Helpful")

    def test_morale_flee(self):
        mon = Monster("Goblin", {"WIL": 8}, hp=4, max_hp=4)
        out = self.rs.morale_check(ScriptedDice([18]), mon)  # 18 > 8 -> fail -> flee
        self.assertTrue(out["fled"])
        self.assertEqual(mon.status, "fled")


class TestRegistry(unittest.TestCase):
    def test_load_and_list(self):
        self.assertTrue(any(r["id"] == "cairn" for r in available()))
        self.assertIsInstance(load_ruleset("cairn"), CairnRuleset)
        with self.assertRaises(KeyError):
            load_ruleset("nonesuch")


class TestSessionOrchestration(unittest.TestCase):
    """Exercise the turn machinery with hand-built referee output (no LLM)."""
    def setUp(self):
        self.rs = load_ruleset("cairn")
        self.state = GameState(ruleset="cairn")
        self.state.party = [self.rs.create_character(Dice(seed=1), "Bea")]
        self.session = Session(self.state, warden=None, ruleset=self.rs, dice=Dice(seed=1))

    def test_spawn_then_resolve_attack(self):
        self.session._spawn([{"name": "Root Goblin", "hp": 4, "weapon_die": "1d6",
                              "abilities": {"STR": 8, "DEX": 14, "WIL": 8}}])
        gob = self.state.find_threat("Root Goblin")
        self.assertIsNotNone(gob)
        self.assertEqual(gob.hp, 4)
        results = self.session._resolve([
            {"kind": "attack", "attacker": "Bea", "target": "Root Goblin", "modifier": "enhanced"}])
        self.assertEqual(results[0]["kind"], "attack")
        self.assertTrue(gob.hp <= 4)

    def test_effects_item_and_status(self):
        self.session._effects([{"kind": "item_gain", "actor": "Bea", "item": "brass key"}])
        self.assertIn("brass key", self.state.party[0].inventory)
        self.session._effects([{"kind": "item_drop", "actor": "Bea", "item": "torch"}])
        self.assertNotIn("torch", self.state.party[0].inventory)

    def test_resolution_bad_actor_is_safe(self):
        # referencing a nonexistent actor must not raise
        out = self.session._resolve([{"kind": "save", "actor": "Nobody", "ability": "STR"}])
        self.assertEqual(out, [])


class TestPersistence(unittest.TestCase):
    """Save → reload round-trip restores the full game (no LLM)."""
    def setUp(self):
        import tempfile
        from engine import store
        self.store = store
        self._tmp = tempfile.mkdtemp()
        self._orig = store.DB_PATH
        store.DB_PATH = os.path.join(self._tmp, "t.db")
        store.init_db()

    def tearDown(self):
        self.store.DB_PATH = self._orig

    def test_roundtrip(self):
        rs = load_ruleset("cairn")
        st = GameState(ruleset="cairn", adventure="the black well")
        pc = rs.create_character(Dice(seed=1), "Bea")
        pc.x, pc.y = 3, 4
        st.party = [pc]
        st.threats = [rs.make_monster(Dice(seed=2),
                     {"name": "Root Goblin", "hp": 4, "x": 7, "y": 5, "kind": "monster"})]
        st.add_event("narration", "You descend into the dark.")
        st.in_combat = True
        st.round = 2

        gid = self.store.create_game("cairn", "Bea", "the black well", st, ["look", "flee"])
        loaded = self.store.load_latest()
        self.assertEqual(loaded["id"], gid)
        self.assertEqual(loaded["human"], "Bea")
        self.assertEqual(loaded["options"], ["look", "flee"])
        rst = loaded["state"]
        self.assertEqual(rst.party[0].name, "Bea")
        self.assertEqual((rst.party[0].x, rst.party[0].y), (3, 4))
        self.assertEqual(rst.threats[0].name, "Root Goblin")
        self.assertEqual((rst.threats[0].x, rst.threats[0].y), (7, 5))
        self.assertTrue(rst.in_combat and rst.round == 2)
        self.assertEqual(rst.log[-1].text, "You descend into the dark.")

    def test_save_updates_same_row(self):
        st = GameState(ruleset="cairn", adventure="a")
        gid = self.store.create_game("cairn", "X", "a", st, [])
        st.round = 9
        self.store.save_game(gid, st, ["onward"])
        loaded = self.store.load_latest()
        self.assertEqual(loaded["id"], gid)
        self.assertEqual(loaded["state"].round, 9)
        self.assertEqual(loaded["options"], ["onward"])


class TestMultiplayer(unittest.TestCase):
    """Seat claiming, AI-fill, and the turn spotlight — no LLM needed."""
    def setUp(self):
        import tempfile
        from engine import store
        from engine.session import Session
        store.DB_PATH = os.path.join(tempfile.mkdtemp(), "mp.db")
        import web
        self.web = web
        rs = load_ruleset("cairn")
        st = GameState(ruleset="cairn")
        bea = rs.create_character(Dice(seed=1), "Bea", is_ai=False)
        thorn = rs.create_character(Dice(seed=2), "Thorn", is_ai=True, persona="dwarf")
        mira = rs.create_character(Dice(seed=3), "Mira", is_ai=True, persona="scout")
        st.party = [bea, thorn, mira]
        self.t = web.Table()
        self.t.session = Session(st, None, rs, Dice())
        self.t.ruleset = rs; self.t.started = True; self.t.human = "Bea"
        import time
        self.t.game_id = None; self.t.owners = {"Bea": "alice"}; self.t.turn = 0
        self.t.seen = {"alice": time.time()}   # alice is an active player
        self.t._sync_ai_flags()

    def test_ai_fills_unclaimed_seats(self):
        p = {c.name: c.is_ai for c in self.t._party()}
        self.assertFalse(p["Bea"])          # claimed by alice
        self.assertTrue(p["Thorn"] and p["Mira"])   # unclaimed => AI

    def test_passive_join_is_host_only(self):
        # host (Bea) is actively held by alice, so a stray tab/2nd browser that
        # just loads the page becomes a spectator — it must NOT grab a companion.
        res = self.t.join("bob")
        self.assertTrue(res["spectator"])
        self.assertIsNone(res["seat"])
        self.assertTrue(self.t.session.state.find_character("Thorn").is_ai)  # still AI
        self.assertTrue(self.t.session.state.find_character("Mira").is_ai)

    def test_explicit_claim_takes_over_ai_seat(self):
        res = self.t.claim("bob", "Thorn")
        self.assertEqual(res["seat"], "Thorn")
        self.assertFalse(self.t.session.state.find_character("Thorn").is_ai)
        # a third human explicitly takes Mira
        self.assertEqual(self.t.claim("carol", "Mira")["seat"], "Mira")
        self.assertFalse(self.t.session.state.find_character("Mira").is_ai)
        # claiming an actively-held seat is refused
        with self.assertRaises(Exception):
            self.t.claim("dave", "Thorn")

    def test_turn_spotlight_advances(self):
        self.assertEqual(self.t._active_idx(), 0)     # Bea
        self.t._advance(); self.assertEqual(self.t._active_idx(), 1)   # Thorn
        self.t._advance(); self.assertEqual(self.t._active_idx(), 2)   # Mira
        self.t._advance(); self.assertEqual(self.t._active_idx(), 0)   # wrap to Bea

    def test_spotlight_skips_the_dead(self):
        self.t.session.state.party[1].status = "dead"   # Thorn falls
        self.t.turn = 0
        self.t._advance()
        self.assertEqual(self.t._active_idx(), 2)        # skip Thorn -> Mira

    def test_idle_host_seat_is_reclaimable(self):
        import time
        # alice holds the host seat (Bea) but wanders off; a returning player
        # (e.g. the same solo tester in a fresh browser) can reclaim it.
        self.assertTrue(self.t.join("bob")["spectator"])  # host actively held
        self.t.seen["alice"] = time.time() - 999          # alice goes idle
        res = self.t.join("erin")                         # erin returns
        self.assertEqual(res["seat"], "Bea")              # reclaims the idle host seat
        self.assertEqual(self.t.owners.get("Bea"), "erin")   # erin now holds it, not alice

    def test_snapshot_control_and_turn(self):
        self.t.claim("bob", "Thorn")                     # bob -> Thorn
        snap = self.t.snapshot("alice")
        self.assertEqual(snap["active"], "Bea")
        self.assertTrue(snap["your_turn"])               # alice holds Bea = active
        names = {c["name"]: c for c in snap["party"]}
        self.assertEqual(names["Bea"]["controlled"], "human")
        self.assertTrue(names["Bea"]["is_you"])          # from alice's view
        self.assertEqual(names["Thorn"]["controlled"], "human")   # bob
        self.assertEqual(names["Mira"]["controlled"], "ai")
        self.assertEqual(snap["players"], 2)

    def test_toggle_player_and_ai_control(self):
        # one player (alice) can hold several seats and flip each independently
        self.t.claim("alice", "Thorn")
        self.assertFalse(self.t.session.state.find_character("Thorn").is_ai)
        self.assertEqual(set(self.t._seats_of("alice")), {"Bea", "Thorn"})
        self.t.release("alice", "Thorn")             # hand Thorn back to the Warden
        self.assertTrue(self.t.session.state.find_character("Thorn").is_ai)
        self.assertEqual(self.t._seats_of("alice"), ["Bea"])
        # releasing an already-AI seat is rejected
        with self.assertRaises(Exception):
            self.t.release("alice", "Thorn")

    def test_cannot_release_another_players_seat(self):
        self.t.claim("bob", "Thorn")
        with self.assertRaises(Exception):          # carol neither owns it nor is host
            self.t.release("carol", "Thorn")


class TestDnD35(unittest.TestCase):
    """D&D 3.5 (d20/SRD) ruleset — fully deterministic, no LLM."""
    def setUp(self):
        self.rs = DnD35Ruleset()

    def _pc(self):
        return Character(
            name="Tark",
            abilities={"STR": 14, "DEX": 12, "CON": 13, "INT": 10, "WIS": 8, "CHA": 10},
            hp=10, max_hp=10, armor=15,
            weapon="longsword", weapon_die="1d8",
            extras={"save_base": {"fort": 2, "ref": 0, "will": 0},
                    "attack_bonus": 5, "attack_mode": "melee", "level": 1})

    def test_ability_modifier(self):
        self.assertEqual([_mod(n) for n in (7, 8, 10, 11, 14, 18)], [-2, -1, 0, 0, 2, 4])

    def test_registered_and_six_abilities(self):
        self.assertIn("dnd35", [r["id"] for r in available()])
        rs = load_ruleset("dnd35")
        self.assertEqual(rs.abilities, ["STR", "DEX", "CON", "INT", "WIS", "CHA"])

    def test_class_inferred_from_persona(self):
        wiz = self.rs.create_character(Dice(seed=7), "Bram", persona="whacky wizard")
        self.assertEqual(wiz.extras["cls"], "wizard")
        self.assertEqual(wiz.weapon_die, "1d6")
        self.assertEqual(wiz.extras["hd"], 4)
        self.assertEqual(set(wiz.abilities), {"STR","DEX","CON","INT","WIS","CHA"})
        self.assertGreaterEqual(wiz.hp, 1)
        self.assertGreaterEqual(wiz.armor, 10)          # AC is 10 + ...
        ftr = self.rs.create_character(Dice(seed=7), "Thorn", persona="gruff dwarf warrior")
        self.assertEqual(ftr.extras["cls"], "fighter")

    def test_save_vs_dc_and_natural_rolls(self):
        pc = self._pc()
        # Reflex DC 15: nat 10 + DEX mod (+1) + ref base 0 = 11 -> fail
        f = self.rs.roll_save(ScriptedDice([10]), pc, "Ref", dc=15)
        self.assertEqual(f["dc"], 15); self.assertFalse(f["success"])
        # Fortitude: nat 12 + CON mod (+1) + fort base 2 = 15 vs DC 15 -> pass
        p = self.rs.roll_save(ScriptedDice([12]), pc, "Fort", dc=15)
        self.assertTrue(p["success"])
        # natural 1 always fails, natural 20 always succeeds
        self.assertFalse(self.rs.roll_save(ScriptedDice([1]), pc, "Fort", dc=1)["success"])
        self.assertTrue(self.rs.roll_save(ScriptedDice([20]), pc, "Will", dc=99)["success"])

    def test_attack_hit_miss_and_crit(self):
        pc = self._pc()
        foe = self.rs.make_monster(Dice(seed=1), {"name": "Orc", "ac": 15, "hp": 20})
        # miss: nat 2 + 5 = 7 vs AC 15
        miss = self.rs.resolve_attack(ScriptedDice([2]), pc, foe)
        self.assertFalse(miss["hit"]); self.assertEqual(foe.hp, 20)
        # hit: nat 14 + 5 = 19 >= 15; damage 1d8 roll 6 + STR mod 2 = 8
        hit = self.rs.resolve_attack(ScriptedDice([14, 6]), pc, foe)
        self.assertTrue(hit["hit"]); self.assertEqual(hit["damage"], 8); self.assertEqual(foe.hp, 12)
        # crit: nat 20 (attack), 5 (damage die), 15 (confirm) -> (5+2)*2 = 14
        crit = self.rs.resolve_attack(ScriptedDice([20, 5, 15]), pc, foe)
        self.assertTrue(crit["critical"]); self.assertEqual(crit["damage"], 14); self.assertEqual(foe.hp, -2)
        self.assertEqual(foe.status, "critical")         # below 0 but above -10 = dying

    def test_death_at_minus_ten(self):
        foe = self.rs.make_monster(Dice(seed=1), {"name": "Goblin", "ac": 14, "hp": 5})
        out = self.rs._apply_damage(Dice(), foe, 16)      # 5 - 16 = -11
        self.assertTrue(out.get("died")); self.assertEqual(foe.status, "dead")

    def test_persistence_roundtrip_keeps_extras(self):
        import tempfile
        from engine import store
        store.DB_PATH = os.path.join(tempfile.mkdtemp(), "d35.db")
        store.init_db()
        st = GameState(ruleset="dnd35")
        st.party = [self.rs.create_character(Dice(seed=3), "Mira", persona="elf ranger")]
        gid = store.create_game("dnd35", "Mira", "test", st, [])
        back = store.load_latest()["state"]
        self.assertEqual(back.party[0].extras["cls"], "ranger")
        self.assertEqual(back.party[0].extras["attack_mode"], "ranged")


if __name__ == "__main__":
    unittest.main(verbosity=2)
