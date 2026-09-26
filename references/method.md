# Method — three passes, then naming

The order is the method. Do not read agent output before finishing pass 1.

Inputs per session (written by `distill.py digest`):
- `user-stream.md` — every human prompt across all selected sessions, chronological, tagged `S03·T12`
- `<S>.user.md` — one session, human side only
- `<S>.dialog.md` — human prompts interleaved with each turn's *final* response; ordinary tool calls collapsed into one `⚙` skeleton line; orchestration kept (`⤷` delegation, `⏰` schedule, `✉` message, `☰` task list, `✎` skill, `◇` plan, `?` question, `⟲` compaction, `✋` rejection, `⛔` interrupt)

## Pass 1 · forward, human only — the intent line

Read `user-stream.md`, then each `<S>.user.md`. You are reconstructing the operator's *policy*.

- **opening move** (T1): outcome or procedure? constraints? how much autonomy granted? what was deliberately left unsaid?
- **steering moves**: redirect, narrow, escalate, approve, reject, interrupt, delegate, schedule, hand over a contract
- **cadence**: prompt length, gaps between prompts (autonomy span), switches between sessions
- **leading words**: exact phrases that recur, or that precede a change in agent behavior
- **naming events**: a vague description replaced by a precise term — what unblocked afterward?

## Pass 2 · forward, dialogue — call and response

Read `<S>.dialog.md`. For each human turn: what result did it get, and was the next prompt a reaction to that result?

Mark: early stop · drift · over-claim · silent failure · rework · harness rescue (cron / loop / teammate / compaction / plan approval) · human gate (approval, rejection, question answered).

## Pass 3 · backward, god's-eye — the critical path (关键时序)

1. State the **end state**: what was delivered or decided, and what was left open.
2. Walk **backward**. For each outcome find the earliest turn that made it inevitable.
3. Keep **3–7 pivots**. Number them in time order: these are the key steps 1-2-3.
4. **Counterfactual test** for each pivot: delete the turn. Does the outcome survive? If yes, it is not a pivot. "What would have happened instead" *is* the answer to "why is this step key".
5. **Hindsight ledger**: what the actors could not know at the time — dead ends, luck, what other sessions were doing in parallel (timeline). Keep hindsight separate from judging the actors.

## Naming — reverse Vocabulary-First (grounded taxonomy)

Let the taxonomy emerge from the data; the lens only disciplines the naming.

- **open coding**: label every pivot and recurring move with a short verb phrase, each grounded in anchors
- **axial coding**: group codes into categories; relate them (enables / prevents / replaces / precedes / compensates)
- **selective coding**: choose the one core category that explains most pivots across sessions — that is the thesis

Each named move gets: preferred term · aliases · one-line definition · evidence anchors · counterfactual · the copyable form (prompt or harness action).
A move without a name is not distilled. A name without evidence is not allowed.

## Cross-session reading (the concurrency question)

With `timeline.md` open, answer from evidence:
- How many sessions ran at once, how long did the agent run without a human prompt (autonomy span), how often did the operator switch?
- What made tasks independent — found, or designed? Where dependencies existed, how were they cut?
- What did the operator *not* review, and what replaced review (result gates, tests, crons, teammates)?
- What kept each goal alive across hours: charter, compaction summary, cron prompt, task list?

## Anti-collage rules (synthesis)

Failure being prevented: a lead that shreds teammates' findings and glues them back with invented filler.

- One mind writes the synthesis after reading all cards. Never concatenate card fragments.
- Every claim carries an anchor `[S03·T12]` or `[timeline]`. Unanchored statements are marked 推测 or cut.
- Do not fill gaps with world knowledge about how people usually work. Missing evidence is reported as missing.
- Contradictions between sessions are reported, not averaged away.
- The operator is described, not flattered: failures and waste are part of the method.
