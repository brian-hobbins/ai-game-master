"""Session orchestration — the turn loop that binds Warden + engine + ruleset.

A turn:
  1. log the declared action
  2. REFEREE (LLM) decides what to resolve
  3. engine spawns any monsters, resolves the dice through the ruleset, and
     applies deterministic effects — mutating state, never the LLM
  4. NARRATOR (LLM) turns the rolled results into prose
  5. scene + narration are logged and returned

All dice flow through self.dice (seedable). The LLM touches none of it.
"""
from __future__ import annotations

from engine.dice import Dice
from engine.state import Feature, GameMap, GameState, Scene
from gm.warden import Warden


class Session:
    def __init__(self, state: GameState, warden: Warden, ruleset, dice: Dice | None = None):
        self.state = state
        self.warden = warden
        self.ruleset = ruleset
        self.dice = dice or Dice()

    # -- lifecycle ----------------------------------------------------------
    def begin(self, premise: str) -> dict:
        narr = self.warden.opening(self.state, premise)
        self._apply_narration(narr)
        return narr

    def take_turn(self, actor_name: str, action: str) -> dict:
        self.state.add_event("action", action, actor=actor_name)
        ref = self.warden.adjudicate(self.state, actor_name, action)

        if ref.get("enter_combat"):
            if not self.state.in_combat:
                self.state.in_combat = True
                self.state.round = 1
            else:
                self.state.round += 1
        self._spawn(ref.get("spawn") or [])
        results = self._resolve(ref.get("resolutions") or [])
        self._effects(ref.get("effects") or [])
        self._move(ref.get("movements") or [])
        if ref.get("leave_combat"):
            self.state.in_combat = False
            self.state.round = 0

        for r in results:
            self.state.add_event("mechanic", r.get("detail", str(r)))

        narr = self.warden.narrate(self.state, actor_name, action, results)
        self._apply_narration(narr)
        narr["results"] = results
        return narr

    def ai_turn(self, character) -> dict:
        """Let an AI-controlled party member decide and take its turn."""
        decision = self.warden.ai_player_action(self.state, character)
        action = decision.get("action", "waits and watches")
        say = decision.get("say", "")
        declared = f'"{say}" — {action}' if say else action
        out = self.take_turn(character.name, declared)
        out["ai_decision"] = decision
        return out

    # -- internals ----------------------------------------------------------
    def _spawn(self, specs: list[dict]) -> None:
        for spec in specs:
            if not isinstance(spec, dict) or not spec.get("name"):
                continue
            if self.state.find_threat(spec["name"]):
                continue
            self.state.threats.append(self.ruleset.make_monster(self.dice, spec))

    def _resolve(self, resolutions: list[dict]) -> list[dict]:
        out: list[dict] = []
        for r in resolutions:
            if not isinstance(r, dict):
                continue
            kind = r.get("kind")
            try:
                if kind == "save":
                    actor = self.state.combatant(r.get("actor", ""))
                    if actor:
                        out.append(self.ruleset.roll_save(
                            self.dice, actor, r.get("ability", "STR"), r.get("reason", ""),
                            dc=r.get("dc")))
                elif kind == "attack":
                    atk = self.state.combatant(r.get("attacker", ""))
                    tgt = self.state.combatant(r.get("target", ""))
                    if atk and tgt:
                        out.append(self.ruleset.resolve_attack(
                            self.dice, atk, tgt,
                            modifier=r.get("modifier", "normal"),
                            reason=r.get("reason", "")))
                elif kind == "reaction":
                    out.append(self.ruleset.reaction_roll(self.dice))
                elif kind == "morale":
                    mon = self.state.find_threat(r.get("actor", ""))
                    if mon:
                        out.append(self.ruleset.morale_check(self.dice, mon))
            except Exception as exc:  # a bad spec shouldn't crash the game
                out.append({"kind": "error", "detail": f"(could not resolve {kind}: {exc})"})
        return out

    def _effects(self, effects: list[dict]) -> None:
        for e in effects:
            if not isinstance(e, dict):
                continue
            kind = e.get("kind")
            actor = self.state.combatant(e.get("actor", ""))
            if kind == "item_gain" and actor and hasattr(actor, "inventory"):
                actor.inventory.append(e.get("item", "something"))
            elif kind == "item_drop" and actor and hasattr(actor, "inventory"):
                item = (e.get("item") or "").lower()
                actor.inventory = [i for i in actor.inventory if i.lower() != item]
            elif kind == "status" and actor:
                actor.status = e.get("status", actor.status)
            elif kind == "rest" and actor and hasattr(actor, "max_hp"):
                res = self.ruleset.short_rest(actor)
                self.state.add_event(
                    "mechanic",
                    f"{actor.name} rests — HP restored to {res['hp']} (+{res['restored']})")

    def _move(self, moves: list[dict]) -> None:
        for mv in moves:
            if not isinstance(mv, dict):
                continue
            tok = self.state.combatant(mv.get("name", ""))
            if tok is not None and "x" in mv and "y" in mv:
                tok.x, tok.y = self._clamp(mv["x"], mv["y"])

    def _clamp(self, x, y):
        w, h = self.state.map.width, self.state.map.height
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            return 0, 0
        return max(0, min(w - 1, x)), max(0, min(h - 1, y))

    def _apply_map(self, mp: dict) -> None:
        if not isinstance(mp, dict) or not mp:
            return
        features = []
        for f in mp.get("features", []) or []:
            if isinstance(f, dict) and "x" in f and "y" in f:
                fx, fy = self._clamp_to(f["x"], f["y"],
                                        mp.get("width", self.state.map.width),
                                        mp.get("height", self.state.map.height))
                features.append(Feature(x=fx, y=fy, kind=f.get("kind", "feature"),
                                        label=f.get("label", "")))
        self.state.map = GameMap(
            width=int(mp.get("width", self.state.map.width)),
            height=int(mp.get("height", self.state.map.height)),
            biome=mp.get("biome", self.state.map.biome),
            features=features,
        )

    @staticmethod
    def _clamp_to(x, y, w, h):
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            return 0, 0
        return max(0, min(int(w) - 1, x)), max(0, min(int(h) - 1, y))

    def _apply_narration(self, narr: dict) -> None:
        sc = narr.get("scene") or {}
        if isinstance(sc, dict) and (sc.get("location") or sc.get("description")):
            self.state.scene = Scene(
                location=sc.get("location", self.state.scene.location),
                description=sc.get("description", self.state.scene.description),
                exits=sc.get("exits", self.state.scene.exits) or [],
            )
        self._apply_map(narr.get("map") or {})
        for p in narr.get("placements", []) or []:
            if isinstance(p, dict):
                tok = self.state.combatant(p.get("name", ""))
                if tok is not None and "x" in p and "y" in p:
                    tok.x, tok.y = self._clamp(p["x"], p["y"])
        text = narr.get("narration", "")
        if text:
            self.state.add_event("narration", text)
