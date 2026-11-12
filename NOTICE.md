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

## D&D 3.5 / d20 System (game ruleset)

This project includes a playable implementation of the **d20 System 3.5** rules,
derived from the **System Reference Document v3.5 (SRD 3.5)**.

> The SRD 3.5 is Open Game Content released by **Wizards of the Coast** under the
> **Open Game License v1.0a (OGL)**. The full license text is available from
> Wizards of the Coast and at <https://www.wizards.com/default.asp?x=d20/oglfaq/20040123>
> (also widely mirrored, e.g. <https://www.d20srd.org/ogl.htm>).

Open Game Content in this repository (derived from the SRD 3.5, distributed under
the OGL v1.0a):

- The `_RULES_DIGEST` text embedded in `rulesets/dnd35.py` — a condensed
  paraphrase of the SRD 3.5 core rules used as context for the AI DM.
- The 3.5 mechanics re-expressed as Python logic in `rulesets/dnd35.py`
  (ability modifiers, saving throws vs DC, attacks vs AC, criticals, the HP/death
  track, class kits, monster building).

**OGL Section 15 — COPYRIGHT NOTICE**

```
Open Game License v 1.0a Copyright 2000, Wizards of the Coast, Inc.
System Reference Document v3.5 Copyright 2000-2003, Wizards of the Coast, Inc.;
authors Jonathan Tweet, Monte Cook, Skip Williams, Rich Baker, Andy Collins,
David Noonan, Rich Redman, Bruce R. Cordell, John D. Rateliff, Thomas Reid,
James Wyatt, based on original material by E. Gary Gygax and Dave Arneson.
AI Game Master d20 3.5 ruleset Copyright 2026, Brian Hobbins.
```

**Product Identity:** "Dungeons & Dragons", "D&D", "Wizards of the Coast", and
related logos and names are **trademarks / Product Identity of Wizards of the
Coast** and are **not** Open Game Content. They are not used in this project's
play text; the ruleset is presented as **"d20 3.5 (SRD)"**. This is an
independent, unofficial work, **not affiliated with or endorsed by** Wizards of
the Coast.

> **Note:** For full OGL compliance when distributing, include the complete text
> of the Open Game License v1.0a (see the link above) alongside this notice. It
> is omitted from this file only to keep the notice short; adding it changes
> nothing else.

## Everything else

All original source code (the engine, the ruleset framework, the AI Warden, the
CLI, and tests) is © 2026 Brian Hobbins and licensed under the **MIT License**
(see `LICENSE`).
