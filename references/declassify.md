# Declassification (消密) — keep the shape, drop the substance

The reader wants *how* the operator works, not *what* the operator works on.
Everything that carries method survives. Everything that carries content is abstracted.

## Three layers

1. **Deterministic** — `distill.py digest` already replaced: secrets and tokens, emails, phone numbers, IPs, URLs (host kept only if allowlisted), home paths, project directory names (→ `P01`…), and every denylist term. Aliases are stable across the run (`private/aliases.json`).
2. **Semantic** — you, while writing cards and the bundle: climb the abstraction ladder below.
3. **Verification** — `distill.py leakcheck public/` plus a red-team teammate, then the operator's sign-off.

## Keep

- sequence and timing of moves; prompt *form* (structure, length, register, constraints, autonomy granted)
- leading words and semantic anchors when they are generic ("god's-eye view", "first principles", "agent team", "set a cron")
- harness mechanics: tool names, counts, schedules, delegation patterns, models
- failure modes and recoveries
- the *kind* of domain, generalized one level up ("LLM training infra", "data pipeline", "web backend")

## Abstract — ladder from specific to role

| class | looks like | becomes |
|---|---|---|
| unpublished research | a named method, ablation result, metric delta, hypothesis | `[RESEARCH-1: training-objective change; result withheld]` |
| internal system | codename, service, repo, product, internal tool | `[SERVICE-A]`, `[REPO-B]` |
| people | colleagues, customers, reviewers, chat partners | `[PERSON-1]` |
| data | dataset, checkpoint, table, bucket names; concrete numbers | `[DATASET-1]`, `[N]` |
| infra | hosts, clusters, IPs, URLs, account and job IDs | `[HOST]`, `[URL]`, `[ID]` |
| code | proprietary snippets | one generic sentence describing the change |
| business | customers, revenue, roadmap, pricing | drop |
| personal life | health, money, family, relationships, job reviews | drop the whole session from the bundle; do not mention it exists |
| personal infra | account-sharing proxies, API relays, keys pasted in prompts | `[PERSONAL-PROXY]`; never describe how it bypasses a provider |

One alias per entity across the whole bundle. Reuse the ones in `private/aliases.json`; add new ones there.
Quotes from prompts: ≤ 25 words, declassified, and only when the *form* is the lesson.

## Never publish

Secrets of any kind · raw or digested transcripts · `private/` (aliases map, denylist, cards) · screenshots of sessions · exact timestamps finer than the hour when they could identify an employer's schedule (round them).

## Denylist

Location: `~/.config/distill-my-session/denylist.txt` (outside any repo). One entry per line:

```
# plain term (case-insensitive)            → replaced by [REDACTED]
AcmeCorp => [COMPANY]
# regex with re: prefix, optional alias
re:proj-[a-z]+-\d+ => [PROJECT]
```

Ask the operator for company names, codenames, colleague names, and paper keywords during the charter. Append them; never echo them into public files or chat summaries.

## Verification gate

1. `distill.py leakcheck <out>/public` exits 0. It also flags real project names from `aliases.json`, denylist hits, secrets, emails, IPs, absolute paths, long high-entropy strings.
2. A red-team teammate that sees **only** `public/` (not the denylist, not `private/`) plays an outsider and answers: *what can I infer about the employer, projects, colleagues, unpublished research?* You judge each inference against what you know is sensitive; fix every real one; rerun 1.
3. Show the operator the file list and the red-team report. Publish only on explicit approval.
