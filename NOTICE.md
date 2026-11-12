# Attribution & third-party content

## Cairn (game ruleset)

This project includes a playable implementation of the **Cairn** tabletop RPG.

> **Cairn** is created by **Yochai Gal**. Website: <https://cairnrpg.com>
> Cairn is licensed under **Creative Commons Attribution-ShareAlike 4.0
> International (CC BY-SA 4.0)**: <https://creativecommons.org/licenses/by-sa/4.0/>

The following parts of this repository are **derived from the Cairn System
Reference Document** and are therefore distributed under **CC BY-SA 4.0**, the
same license as the original:

- `rulesets/cairn_data/cairn-srd.md` — the Cairn SRD (first edition), retrieved
  from <https://github.com/yochaigal/cairn>.
- `rulesets/cairn_data/rules-summary.md`
- The `_RULES_DIGEST` text embedded in `rulesets/cairn.py` (a condensed
  paraphrase/excerpt of the SRD used as context for the AI Warden).

Changes made: the SRD rules were summarized into a compact "rules digest" and
re-expressed as Python logic (character creation, saves, combat, critical
damage, morale, reactions). These derivative works remain under CC BY-SA 4.0.

This project is an independent, unofficial work and is **not affiliated with or
endorsed by** Yochai Gal or Cairn.

## Everything else

All original source code (the engine, the ruleset framework, the AI Warden, the
CLI, and tests) is © 2026 Brian Hobbins and licensed under the **MIT License**
(see `LICENSE`).
