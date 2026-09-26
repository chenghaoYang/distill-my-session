# Output schema — field names are fixed

## Layout

```
<out>/
  CHARTER.md            phase 0; pasted into every teammate prompt
  STATE.md              progress checkpoint; resume from here after compaction or restart
  private/              never published (.gitignore'd)
    index.json  aliases.json  timeline.json
    user-stream.md  digests/<S>.user.md  digests/<S>.dialog.md
    cards/<S>.md        one per deeply-read session
    redteam.md
  public/               the only publishable directory
    README.md  lexicon.md  trajectories.md  concurrency.md  harness.md  prompts.md  method.md
```

## Session card — `private/cards/<S>.md`

```markdown
---
session: S03
project: P02            # alias only
source: claude-code     # or codex
machine: m1
window: 2026-09-24 10h → 2026-09-25 01h   # hour precision
active_hours: 5.2
human_turns: 14
autonomy_span_max: 3h10m
harness: [teammates×4, cron×2, compaction×1, plan-mode]
models: [ ... ]
---
## Goal
- stated: … [T1]
- evolved: … [T5][T9]
- kept alive by: charter / compaction summary / cron prompt / task list / nothing … [anchors]

## Intent line            (pass 1: 5–10 lines on how the human steered; cadence; leading words)

## Critical path — 关键时序   (pass 3: 3–7 pivots, time order)
1. [T1] **<move>** — what happened. **Why key:** <counterfactual: without it, …>
2. [T4→T5] **<move>** — … **Why key:** …

## Hindsight ledger       (what the actors could not see at the time; parallel sessions)

## Open codes
| code | anchor | evidence (≤25 words, declassified) |

## Leading words
| phrase (verbatim, declassified) | anchor | what it triggered |

## Harness
| mechanism | anchor | effect |

## Friction
| failure (early stop / drift / over-claim / rework / …) | anchor | recovery |

## Declassification notes  (classes abstracted, never the values)
```

## Public bundle

Write in the charter's language; terms of art stay in English. Third-person narration. Every non-obvious claim carries an anchor.

**README.md** — the front door (30-second read)
1. one-line thesis (the core category) + one short 金句
2. 结论前置: 3–5 threshold concepts, each one line with anchors
3. the concurrency architecture (mermaid `flowchart`), drawn from evidence
4. doc map (links to the other files)
5. one worked example: a single trajectory's key steps 1-2-3 in five lines
6. closing couplet, one line zh + one line en

**lexicon.md** — the Vocabulary-First pack of the method
`seed terms` · `core lexicon` (named moves) · `shibboleths` (leading words) · `semantic anchors` · `trigger terms` · `threshold concepts` · `entry vocabulary` · `concept map` (edges + mermaid `graph`)

Core lexicon entry, fixed fields:

| term | aliases | definition | anchors | counterfactual | copyable form |

**trajectories.md** — 3–6 representative sessions (chosen to cover different categories, not the longest). Per session: goal · key steps 1-2-3 with *why key* · hindsight · which lexicon terms it instantiates.

**concurrency.md** — numbers from `timeline.md` (peak parallel sessions, autonomy span, switches/hour, prompts/active hour), the gantt, and the answers to the cross-session questions in method.md.

**harness.md** — per mechanism (teammates/subagents, cron/loop/wakeups, compaction and goal-keeping, plan mode, task lists, skills, workflows): when the operator reached for it, what it rescued, what it cost. Anchored.

**prompts.md** — prompt patterns, each as: name (from the lexicon) · when · template with slots · one declassified exemplar · what it triggers. Include delegation prompts the lead agent wrote to teammates.

**method.md** — how this bundle was produced (so a reader can distill their own sessions), scope and sample size, what was declassified (classes), limitations and biases.

## Principle format (used in README and lexicon when arguing a claim)

`命题 (claim)` → `证据 (anchors)` → `反事实 (what breaks without it)` → `用法 (the copyable move)`
