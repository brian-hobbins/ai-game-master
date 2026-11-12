# AI Warden — an AI Game Master for tabletop RPGs

Play a tabletop role-playing game with an **AI Game Master**. Humans play the
heroes; the AI runs the world, voices every NPC, adjudicates the rules, and can
**fill empty party seats with AI players** when you don't have enough people for
a session.

The first supported system is **[Cairn](https://cairnrpg.com)** — a lean,
lethal, fiction-first adventure game — but rulesets are **pluggable**, so
D&D 5e, OSRIC, Fate, or a homebrew system can be dropped in behind the same
engine and AI.

> **Design thesis:** the language model should *tell the story*, not *do the
> math*. A deterministic, fully-tested engine owns every die roll, hit point,
> and death save; the AI only decides *what* should happen in the fiction and
> narrates the results the engine hands back. That split is what keeps an AI GM
> from hallucinating rules — and it's the interesting part.

---

## How it works

Each turn runs a small two-role agent loop. The AI never sees a random number
generator; the engine never writes prose.

```
            player's declared action
                      │
                      ▼
        ┌──────────────────────────┐     "what dice must be rolled?"
        │  AI WARDEN · REFEREE role │ ──► resolutions: saves, attacks,
        │       (language model)    │     reactions, morale, spawns, effects
        └──────────────────────────┘
                      │  (JSON, no prose, no numbers)
                      ▼
        ┌──────────────────────────┐     rolls the actual dice (seedable),
        │   ENGINE + RULESET        │ ──► applies damage / critical / death
        │   (pure Python, tested)   │     per the system's rules, mutates state
        └──────────────────────────┘
                      │  (structured, audited results)
                      ▼
        ┌──────────────────────────┐     "narrate exactly these results"
        │  AI WARDEN · NARRATOR role│ ──► vivid 2nd-person narration + updated
        │       (language model)    │     scene + suggested options
        └──────────────────────────┘
```

AI-controlled party members use a third prompt role to decide an in-character
action, which is then fed through the exact same loop as a human's.

## Quickstart

No dependencies beyond Python 3.10+. The Warden runs on either backend:

```bash
# Uses your authenticated `claude` CLI (your subscription — no API key):
python3 play.py --name Bea --premise "The village well has run black."

# …or the Anthropic API (cheaper/faster per call):
AIGM_BACKEND=api ANTHROPIC_API_KEY=sk-... python3 play.py --name Bea

# Add AI party members to fill out the table:
python3 play.py --name Bea \
  --companions "Thorn:gruff dwarf sellsword;Mira:wary elven scout"
```

Type what your character does; `/sheet` shows the party, `/look` re-describes
the scene, `/quit` exits. Pass `--seed N` for a reproducible run.

### A real turn (seed 11)

```
You climb down into the well to see what's making the water black.

⚙ Bea rolls 3 vs DEX 14 — PASS
» You loop the rusted hook over the crank-arm and start down hand over hand…
  your boots find seams in the slick stone without a single slip. In the black
  water you catch pale, swollen egg-sacs pulsing along the far wall — and two
  flat eyes open just under the surface to fix on you.
```

The `3 vs DEX 14` was rolled by the engine; the Warden narrated that exact
outcome and telegraphed the threat instead of ambushing — Cairn's design in
action.

## Swapping rulesets

A ruleset is one class implementing [`rulesets/base.py`](rulesets/base.py)
(character creation, saves, attacks, death rules, and a compact rules digest
for the AI). Register it and it's selectable:

```python
# rulesets/__init__.py
_REGISTRY = {
    CairnRuleset.id: CairnRuleset,
    # "5e":    DnD5eRuleset,     # add a class, nothing else changes
    # "osric": OSRICRuleset,
}
```

```bash
python3 play.py --ruleset cairn      # (more to come)
```

The engine, the turn loop, and the Warden prompts are all written against the
interface, so neither they nor the CLI change when you add a system.

## Project layout

```
engine/      deterministic core — dice, game state, the turn session loop
rulesets/    pluggable systems — base interface + Cairn (+ the Cairn SRD data)
gm/          the AI Warden — LLM client, prompt roles, warden wrapper
play.py      terminal client (milestone 1: the core loop)
tests/       16 deterministic tests — engine & rules, no network needed
```

Run the tests:

```bash
python3 -m unittest tests.test_engine -v
```

## Roadmap

- [x] Deterministic, tested rules engine (dice, Cairn mechanics, death spiral)
- [x] Pluggable ruleset framework
- [x] AI Warden: referee + narrator two-role loop
- [x] AI-controlled party members (fill empty seats)
- [x] Playable single-table CLI
- [ ] Web + multiplayer front end (several humans join a session; AI fills the rest)
- [ ] Persistent campaigns (SQLite save/resume) & shared session log
- [ ] Additional rulesets (D&D 5e SRD, …) behind the same engine
- [ ] Combat initiative tracker UI, character-creation wizard with ability swaps

## License

Original code: **MIT** (see [`LICENSE`](LICENSE)).
Cairn rules content: **CC BY-SA 4.0**, © Yochai Gal — see [`NOTICE.md`](NOTICE.md).
Unofficial; not affiliated with or endorsed by Cairn.
