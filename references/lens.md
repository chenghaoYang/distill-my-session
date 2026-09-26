# Lens — Vocabulary-First, run in reverse

Adapted from [justinatusa/vocabulary-first](https://github.com/justinatusa/vocabulary-first) (MIT).
If the network is available, skim the live `docs/02-vocabulary-family.md` and `docs/03-bidirectional-usage.md` first; the author keeps refining them. This file is the offline compression.

## The one idea

> Domain vocabulary is the API between the learner and the model. Name things first; then ask for depth or work.
> 命名精度，预测协作速度。

Vocabulary-First has two directions:

- **reverse** — use an umbrella term to make the model emit a domain's vocabulary (build the map)
- **forward** — hand that vocabulary back as a semantic contract to get explanations, plans, code (do the work)

This skill is the reverse direction applied to one domain: **the operator's own way of working with agents**.
Trajectories go in; a vocabulary of named moves comes out. The reader then runs it forward in their own sessions.
Tacit know-how that cannot be named has not been distilled yet.

## Terms → what they become in a distillation

| Vocabulary-First term | Role here | What to produce |
|---|---|---|
| **seed terms** | 8–12 entry words someone needs to talk about this operator's method | first section of `lexicon.md` |
| **core lexicon / glossary** | the named moves = the taxonomy you induce (grounded, not imposed) | one entry per move: preferred term, aliases, definition, anchors, counterfactual, copyable form |
| **shibboleths / high-signal jargon** | the operator's literal *leading words*: phrases in prompts that reliably change agent behavior | phrase · when used · what it triggered · evidence |
| **semantic anchors** | short names of external methods the operator invokes that activate a whole schema in the model ("first principles", "TDD", "god's-eye view") | list with the schema each activates |
| **trigger terms** | words that make the *harness* act (/loop, cron, agent team, plan mode, a skill name) | map: phrase → mechanism |
| **threshold concepts** | 3–5 insights that, once crossed, change how a reader operates (e.g. why N sessions stay reviewable) | README core; each one argued with evidence |
| **entry vocabulary** | novice complaint → preferred term ("review 不过来" → review bottleneck → result gate) | a table the reader can self-diagnose with |
| **concept map** | relations between moves | `A —enables→ B` edges and a mermaid graph |
| **controlled vocabulary** | one preferred term per move; aliases mapped; deprecated terms kept | enforced across all files |
| **vocabulary gap detection** | a stalled trajectory is often a missing word, not missing capability | look for *naming events*: the turn where a vague description became a precise term, and what unblocked after it |
| **semantic compression / named pointer** | a prompt that uses a name instead of paragraphs | quote these as exemplars of good prompts |
| **glossary as semantic contract** | charters, CLAUDE.md/AGENTS.md, plan files, goal statements that bind later turns | note which contract held the goal alive |
| **advance organizer / scaffolding** | how the operator front-loads structure before work | often the opening move |

## Evaluation (from the source)

Judge a move by fewer round-trips and less drift into neighbor domains — not by how long the vocabulary is.

## Writing register

Third-person narration ("the operator", "the lead", "a teammate"), as the source repo does: easy to reread, easy to forward, and it keeps the operator's identity out of the prose.
Use terms of art over metaphors; ban undefined evaluative adjectives (fast, good, elegant) unless defined.
