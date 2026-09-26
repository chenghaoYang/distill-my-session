---
name: distill-my-session
description: Distill the user's own past agent sessions (Claude Code, Codex and Grok Build; one or several machines) into a declassified, publishable bundle about HOW they work — their prompts and leading words, how they run many sessions in parallel, and how the harness (teammates/subagents, cron and loops, compaction, plan mode) carried long tasks — written as a philosophy of practice: named moves, key sequences (关键时序 1-2-3), and why each step mattered. Uses Vocabulary-First in reverse. Use when the user asks to distill, export, review, 复盘 or 蒸馏 their sessions, trajectories, goals, prompts or parallel-agent workflow, or to share them on GitHub so others can learn from them. Not for summarizing only the current conversation.
argument-hint: "[scope: 7d | since 2026-09-01 | project X | codex only] [lang zh|en]"
---

# Distill My Session

A working method is a vocabulary. This skill runs Vocabulary-First in reverse on the operator's own trajectories — trajectories in, named moves out — so a reader can run those moves forward in their own sessions. Distill *how* (prompts, sequencing, harness use, concurrency), never *what* (company work, unpublished research).

Tool: `python3 <this skill's base directory>/scripts/distill.py <scan|digest|timeline|suggest|leakcheck>` — stdlib only; `--help` on each. It reads Claude Code, Codex and Grok Build transcripts, folds subagent threads into their parent, and leaves out programmatic runs (Agent SDK, `codex exec`) unless `--include-sdk`. Read references only when their step comes up: [lens](references/lens.md) · [method](references/method.md) · [declassify](references/declassify.md) · [output schema](references/output-schema.md) · [team prompts](references/team.md) · [charter template](assets/charter.md).

## Inputs — ask only for what is missing

| slot | default |
|---|---|
| scope: window, sources, machines, projects | last 7 days; local `~/.claude/projects`, `~/.codex/sessions`, `~/.grok/sessions` |
| reader | a peer who runs ≤3 sessions and reviews every change by hand |
| declassification | always ask: employer, codenames, colleagues' names, paper topics |
| out | `~/distill-runs/<yyyymmdd>`: outside every repository, so `private/` can never be committed by accident |
| language | the user's language; terms of art stay in English |

Other machines: copy their stores over (`rsync -a host:~/.claude/projects/ ./inbox/host/claude/`) and pass `--src claude@host:./inbox/host/claude` (likewise `codex@host:`, `grok@host:`).
Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30): what is not on disk cannot be distilled, so say so when the requested window reaches past it.

## Protocol

0. **Charter — the first session writes the prompt.** Read lens.md (plus the live `github.com/justinatusa/vocabulary-first` docs if reachable). Run `scan --since … --out <out>` (scan flags likely personal sessions with ⚑), then `digest` with the same scope, then `suggest --out <out> --dialog`. Show the operator the scan table and the suggested terms; the ones they confirm go into `~/.config/distill-my-session/denylist.txt` (kept across runs) or `<out>/private/denylist.txt` (this run only). Sessions about the operator's personal life are excluded outright. Fill `assets/charter.md` into `<out>/CHARTER.md`: goal, reader, 3–5 questions, a deep-read set of 6–12 sessions chosen for coverage of different kinds of work (not for length), and the declassification rules. **Stop for approval.** This is the only checkpoint before publishing.
1. **Digest — deterministic.** Re-run `digest` and `timeline` on the approved scope (always re-run `digest` after the denylist changes). Work from digests; never paste raw `.jsonl` into context.
2. **Read — fan out.** Spawn readers with the prompt in team.md, 1–3 deep-read sessions each (about 150 kB of digest per reader); each writes `private/cards/<S>.md`. Do not re-run `digest` while readers work: turn labels can shift and break their anchors. The three passes run in order: human side only → dialogue → backward from the end state with the counterfactual test. Without subagents, go one session at a time and write each card before starting the next. Update `STATE.md` after every card.
3. **Synthesize — one mind.** Read `user-stream.md`, `timeline.md` and all cards (not the digests). Induce the taxonomy (open → axial → selective coding), choose the core category, then write `public/` per output-schema.md. Every claim carries an anchor such as `[S03·T12]`.
4. **Verify the declassification.** Run `leakcheck <out>/public` until it reports 0 blocking. Then spawn the red team from team.md: a fresh teammate that sees **only** `public/` and reports what an outsider could infer about the employer, projects, people and research. Fix, and re-run the check.
5. **Hand over.** Show the file list, the KPI table and the red-team verdict. Push, gist or copy off the machine only after explicit approval, and only `public/`.

## Long runs

More than ~6 deep-read sessions is a long-horizon task. Keep `STATE.md` current: phase, cards done, next step. If the harness offers scheduled wakeups (`/loop`, cron), set a 30–60 min heartbeat that reads STATE.md and resumes, and delete it when done. After a compaction, reread CHARTER.md and STATE.md before doing anything else.

## Failure modes

| symptom | cause | response |
|---|---|---|
| the taxonomy reads like a generic prompt-engineering listicle | names came from world knowledge, not the data | redo open coding from anchors only |
| the synthesis reads as stitched fragments | collage: fragments glued with invented filler | reread the cards; rewrite from the core category |
| a claim has no anchor | invented glue | anchor it, mark it 推测, or cut it |
| every step looks equally important | the backward pass was skipped | counterfactual test; keep 3–7 pivots |
| content shows through quotes | quoting substance instead of form | quote form only, ≤25 words, abstracted |
| the reader cannot act on it | no copyable form | every lexicon term needs a prompt or a harness move |
| the digest is too large for context | scope too wide | narrow the window, raise `--min-human`, or fan out further |
| readers report digest problems | parser gap or redaction gap | note the class in method.md limitations; fix the script before the next run, never hand-edit digests |
