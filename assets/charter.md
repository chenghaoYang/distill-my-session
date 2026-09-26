# Distillation Charter

> Phase 0 output. The first session writes the prompt; the work starts only after the operator approves this page.
> Every teammate receives this file verbatim.

## Goal
<one sentence: what the reader can do after reading that they could not do before>

## Reader
<who they are, what they already do; e.g. "runs ≤3 sessions, reviews every diff by hand, loses long tasks to early stops">

## Questions the bundle must answer
1. <e.g. how does the operator run many sessions at once without drowning in review?>
2. <e.g. what do the operator's prompts contain that the reader's do not?>
3. <e.g. how does the harness keep a task moving for hours without the human?>
4. <…>

## Scope
- sources / machines: <claude-code, codex; m1, m2>
- window: <since … until …>
- sessions for deep reading: <S01, S04, … (why each: category coverage)>
- sessions for timeline only: <all in window>
- excluded: <projects or sessions the operator vetoed>

## Lens
Vocabulary-First in reverse (references/lens.md). Output language: <zh with English terms of art | en>.

## Declassification
- denylist: ~/.config/distill-my-session/denylist.txt (<n> entries; never quoted here)
- domain generalization: <P01 → "LLM training infra", P02 → "internal data tooling", …>
- extra rules from the operator: <…>

## Deliverables
public/: README.md, lexicon.md, trajectories.md, concurrency.md, harness.md, prompts.md, method.md

## Done when
- every question above is answered with anchors
- leakcheck passes and the red-team report has no open finding
- the operator has approved the file list
