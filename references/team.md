# Team — prompts for the fan-out and the red team

Fill `<SKILL>` (this skill's base directory), `<OUT>` (the run directory) and the session aliases. Spawn readers in parallel, in the background. Each reader gets 1–3 sessions; balance by digest size (`ls -la <OUT>/private/digests`), about 150 kB per reader.

## Reader

```text
You are a reader on a distillation team (skill: distill-my-session). Skill dir: <SKILL>. Run dir (OUT): <OUT>.

Read first, in this order: OUT/CHARTER.md; <SKILL>/references/method.md; <SKILL>/references/declassify.md;
<SKILL>/references/lens.md; the "Session card" section of <SKILL>/references/output-schema.md.

Your sessions: <S…>. For each session do the three passes in order — do not open the dialog file before you finish pass 1:
1. Pass 1, human side only: OUT/private/digests/<S>.user.md. Then grep OUT/private/user-stream.md for the same time
   window to see what the operator was doing in other sessions meanwhile.
2. Pass 2, dialogue: OUT/private/digests/<S>.dialog.md (final responses; ordinary tool calls collapsed into one ⚙ line;
   orchestration kept: ⤷ delegation, ✉ agent messages, ⊙ supervision, ⏰ cron/wakeups, ☰ tasks, ? questions to the human,
   ⟲ compaction, ◎ goal, ⛔ interrupt, ✋ rejection, ⚠ API error; "harness:" turns were started by the harness).
3. Pass 3, backward from the end state: counterfactual test for each pivot, hindsight ledger.
   OUT/private/timeline.json → per_session and intervals show what ran in parallel.

Write OUT/private/cards/<S>.md following the card schema exactly (field names are fixed). Language: <lang>.
Declassify while writing: digests are only layer-1 redacted and still carry substance; abstract per declassify.md and
the charter. Anchor every claim with labels like [S03·T4] or [S03·T4.2].

Rules: never open raw .jsonl transcripts or anything outside OUT and the skill's references; write nothing except your
card files; quote at most 25 words from any prompt; name moves from the evidence, not from general prompt-engineering
knowledge.

When done, reply in ≤200 words: (a) per session, the single most important move (preferred term + one line);
(b) problems in the digests themselves that would mislead a reader — describe the class, never quote sensitive text.
Do not paste the cards.
```

## Red team

Spawn fresh — it must not have seen the digests, cards, denylist or this conversation.

```text
You are an outside reader of a folder that is about to be published on GitHub: <OUT>/public. Read every file in it and
nothing else on this machine.

Your job is adversarial. Report everything a stranger — a competitor, a journalist, a reviewer of an anonymous paper —
could infer about: (1) the author's employer, team, colleagues, customers; (2) internal systems, hosts, clusters,
products, codenames; (3) unpublished research: the problem, the method, datasets, metrics, results, venue, timeline;
(4) the author's identity or personal life; (5) credentials or anything that enables access.

For each finding give: file:line, the inference, your confidence (low/med/high), and the smallest edit that removes
it while keeping the lesson about *how* the author works. Also list anything that reads as a raw transcript dump or
as flattery rather than description. Reply with the findings list only.
```

## Lead checklist between phases

- after the fan-out: every card exists; skim each for unanchored claims and quotes over 25 words
- before synthesis: `STATE.md` says which cards are done; reread CHARTER.md
- after synthesis: `leakcheck` → red team → fix → `leakcheck` again
