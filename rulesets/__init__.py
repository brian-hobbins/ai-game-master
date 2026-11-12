"""Ruleset registry — the swap-a-ruleset entry point.

Register systems here by id. Adding D&D 5e / OSRIC / Fate later is a one-line
addition plus the new module; the engine and Warden are unchanged.
"""
from __future__ import annotations

from rulesets.base import Ruleset
from rulesets.cairn import CairnRuleset
from rulesets.dnd35 import DnD35Ruleset

_REGISTRY: dict[str, type[Ruleset]] = {
    CairnRuleset.id: CairnRuleset,
    DnD35Ruleset.id: DnD35Ruleset,
    # "5e":   DnD5eRuleset,     # <- future
    # "osric": OSRICRuleset,    # <- future
}


def available() -> list[dict]:
    return [{"id": c.id, "name": c.name, "version": c.version,
             "warden_title": c.warden_title, "license": c.license}
            for c in _REGISTRY.values()]


def load_ruleset(ruleset_id: str = "cairn") -> Ruleset:
    key = (ruleset_id or "cairn").lower()
    if key not in _REGISTRY:
        raise KeyError(f"Unknown ruleset {ruleset_id!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[key]()
