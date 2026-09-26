#!/usr/bin/env python3
"""distill.py — the deterministic half of the distill-my-session skill (stdlib only, Python >= 3.9).

  scan       list sessions in scope with stats                      (writes <out>/private/index.json)
  digest     declassified digests: user-stream, <S>.user.md, <S>.dialog.md
  timeline   concurrency: active intervals, peak parallelism (sessions and agents), autonomy, gantt, heat strip
  suggest    candidate denylist terms that survived layer-1 redaction (for the operator to review)
  leakcheck  scan a directory (normally <out>/public) for anything that must not be published

Sources: --src KIND[@MACHINE]:PATH, repeatable. KIND is `claude` (…/.claude/projects), `codex` (…/.codex/sessions)
or `grok` (…/.grok/sessions). Default: whichever of those exist on this machine (+ ~/.codex/archived_sessions).
Programmatic runs (Claude Agent SDK `sdk-cli`, `codex exec`) are left out unless --include-sdk.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from redact import CONFIG_DIR, Redactor, leakcheck, load_list  # noqa: E402
from sources import (GLYPH_STAT, ORCH, Ev, Session, fold_codex_children, one_line,  # noqa: E402
                     parse_claude, parse_codex, parse_grok)

HOME = Path.home()
LIMITS = dict(human=3000, final=1800, delegate=1200, result=500, compact=2500, wake=500, qa=400, narr=240, stream=300, first=160)
WAKE_LABEL = {"resume": "app resumed the agent after a quit or usage limit", "notify": "background task reported",
              "teammsg": "message from this session's own teammate/subagent", "peer": "message from another session",
              "cron": "cron fired", "loop": "loop fired", "goal": "goal hook pushed on", "automation": "automation heartbeat",
              "task": "task from parent agent"}


HEAD_RE = re.compile(r"(?m)^(#{1,6})\s")


def clip(text: str, n: int) -> str:
    text = HEAD_RE.sub(lambda m: "▸" * len(m.group(1)) + " ", (text or "").strip())
    if len(text) <= n:
        return text
    head, tail = int(n * 0.75), int(n * 0.2)
    return f"{text[:head].rstrip()} […{len(text) - head - tail} chars…] {text[-tail:].lstrip()}"


# ------------------------------------------------------------ discovery ----
def parse_src(spec: str):
    kind, _, path = spec.partition(":")
    kind, _, machine = kind.partition("@")
    return kind, machine or "local", Path(path).expanduser()


def discover(srcs: list[str], since: datetime | None):
    if not srcs:
        srcs = [f"claude:{HOME / '.claude/projects'}", f"codex:{HOME / '.codex/sessions'}",
                f"codex:{HOME / '.codex/archived_sessions'}", f"grok:{HOME / '.grok/sessions'}"]
    for spec in srcs:
        kind, machine, root = parse_src(spec)
        if not root.exists():
            continue
        if kind == "claude":
            files = list(root.glob("*/*.jsonl"))
        elif kind == "codex":
            files = list(root.rglob("rollout-*.jsonl"))
        elif kind == "grok":
            files = [p.parent for p in root.glob("*/*/summary.json")]
        else:
            sys.exit(f"unknown source kind: {kind} (use claude, codex or grok)")
        for f in files:
            try:
                probe = f / "updates.jsonl" if f.is_dir() else f
                if since and datetime.fromtimestamp(probe.stat().st_mtime, tz=timezone.utc) < since:
                    continue
            except OSError:
                continue
            yield kind, machine, f


def parse_when(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d+)([hdw])", s.strip())
    if m:
        n, u = int(m.group(1)), m.group(2)
        return datetime.now(timezone.utc) - timedelta(hours=n * {"h": 1, "d": 24, "w": 168}[u])
    dt = datetime.fromisoformat(s)
    return (dt if dt.tzinfo else dt.astimezone()).astimezone(timezone.utc)


def load_sessions(args) -> tuple[list[Session], Counter]:
    since, until = parse_when(args.since), parse_when(args.until)
    parsed = []
    for kind, machine, f in discover(args.src, since):
        s = {"claude": parse_claude, "codex": parse_codex, "grok": parse_grok}[kind](f, machine)
        if s:
            parsed.append(s)
    out, dropped = [], Counter()
    for s in fold_codex_children(parsed):
        if since and s.end < since or until and s.start > until:
            continue
        if s.kind == "programmatic" and not args.include_sdk:
            dropped["programmatic"] += 1
            continue
        cwd = (s.cwd or "").lower()
        if args.project and not any(p.lower() in cwd for p in args.project):
            continue
        if args.exclude and any(p.lower() in cwd for p in args.exclude):
            continue
        if sum(1 for e in s.events if e.kind in ("human", "command")) < args.min_human:
            dropped["below --min-human"] += 1
            continue
        out.append(s)
    out.sort(key=lambda s: s.start)
    return out, dropped


# ---------------------------------------------------------------- turns ----
@dataclass
class Turn:
    label: str
    trigger: str            # human command wake:<kind> resume
    ts: datetime
    head: Ev | None
    body: list = field(default_factory=list)

    @property
    def end(self) -> datetime:
        return self.body[-1].ts if self.body else self.ts

    def final(self) -> tuple[str, str]:
        narrs = [e for e in self.body if e.kind == "narr"]
        if not narrs:
            return "", "none"
        finals = [e for e in narrs if e.meta.get("final")]
        if finals:
            return finals[-1].text, "ok"
        ends = [e for e in narrs if e.meta.get("stop") == "end_turn"]
        if ends:
            mid = ends[-1].meta.get("mid")
            return "\n\n".join(e.text for e in narrs if e.meta.get("mid") == mid), "ok"
        if narrs[-1].meta.get("phase") == "final_answer":
            return narrs[-1].text, "ok"
        return narrs[-1].text, "unfinished"


def build_turns(s: Session) -> list[Turn]:
    turns: list[Turn] = []
    n_h = n_sub = 0
    cur = Turn("T0", "resume", s.start, None)
    last_h: Ev | None = None
    for e in s.events:
        if e.kind in ("human", "command"):
            if last_h and e.name == last_h.name and (e.ts - last_h.ts).total_seconds() < 120 and e.text == last_h.text:
                last_h.meta["repeats"] = last_h.meta.get("repeats", 1) + 1
                continue
            if last_h and e.name == last_h.name and (e.ts - last_h.ts).total_seconds() < 300 and len(last_h.text) >= 12 \
                    and e.text.startswith(last_h.text[: max(12, len(last_h.text) - 4)]) and len(e.text) > len(last_h.text):
                last_h.text, last_h.meta["revised"] = e.text, True      # sent early, then re-sent in full
                continue
            last_h = e
            n_h, n_sub = n_h + 1, 0
            if cur.head or cur.body:
                turns.append(cur)
            cur = Turn(f"T{n_h}", e.kind, e.ts, e)
        elif e.kind == "wake":
            n_sub += 1
            if cur.head or cur.body:
                turns.append(cur)
            cur = Turn(f"T{n_h}.{n_sub}", f"wake:{e.name}", e.ts, e)
        else:
            cur.body.append(e)
    if cur.head or cur.body:
        turns.append(cur)
    return turns


def active_intervals(stamps: list[datetime], gap: timedelta) -> list[tuple[datetime, datetime]]:
    out: list[list[datetime]] = []
    for t in stamps:
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t
        else:
            out.append([t, t])
    return [(a, max(b, a + timedelta(minutes=1))) for a, b in out]


RUN_GAP = timedelta(minutes=255)   # a run survives silences up to ~4h (hourly crons, 4-hourly heartbeats), not longer


def self_run(stamps: list[datetime], x: datetime, y: datetime) -> float:
    """Wall-clock span the agent kept producing after a human prompt at x, until the next prompt y or a silence > RUN_GAP."""
    last = x
    for t in stamps:
        if t < x:
            continue
        if t >= y or t - last > RUN_GAP:
            break
        last = t
    return (last - x).total_seconds()


def session_stats(s: Session, gap: timedelta) -> dict:
    turns = build_turns(s)
    tools = Counter(e.name for e in s.events if e.kind in ("tool", "orch"))
    orch = Counter(GLYPH_STAT[ORCH[e.name]] for e in s.events if e.kind == "orch")
    ivs = active_intervals(s.stamps, gap)
    human = [e for e in s.events if e.kind in ("human", "command")]
    marks = [e.ts for e in human] + [s.end + timedelta(seconds=1)]
    spans = [sum(max(0.0, (min(b, y) - max(a, x)).total_seconds()) for a, b in ivs) for x, y in zip(marks, marks[1:])]
    # wall-clock span the agent kept producing after a human prompt (harness-driven turns included)
    runs = [self_run(s.stamps, x, y) for x, y in zip(marks, marks[1:])]
    wakes = Counter(e.name for e in s.events if e.kind == "wake")
    finals = Counter(t.final()[1] for t in turns if t.trigger in ("human", "command"))
    return dict(
        kind=s.kind, start=s.start.isoformat(), end=s.end.isoformat(),
        active_h=round(sum((b - a).total_seconds() for a, b in ivs) / 3600, 2),
        human_turns=len(human), steers=sum(1 for e in human if e.meta.get("steer")),
        harness_turns=sum(wakes.values()), wakes=dict(wakes), human_chars=sum(len(e.text) for e in human),
        tool_calls=sum(tools.values()), top_tools=tools.most_common(6), orch=dict(orch),
        subagents=len(s.subs), teammates=sum(1 for x in s.subs if x.get("teammate")),
        bg_agents=sum(1 for e in s.events if e.kind == "orch" and e.name in ("Agent", "Task", "spawn_agent") and ("bg" in e.text or "team" in e.text)),
        personal=bool(PERSONAL_RE.search(" ".join(e.text for e in human[:6]))),
        compactions=sum(1 for e in s.events if e.kind == "compact" and e.name == "boundary")
        or sum(1 for e in s.events if e.kind == "compact"),
        goals=sum(1 for e in s.events if e.kind == "goal" and e.name == "set"),
        interrupts=sum(1 for e in s.events if e.kind == "interrupt"), rejects=sum(1 for e in s.events if e.kind == "reject"),
        api_errors=sum(1 for e in s.events if e.kind == "apierr"), unfinished_turns=finals.get("unfinished", 0) + finals.get("none", 0),
        autonomy_max_min=round(max(spans) / 60, 1) if spans else 0.0,
        self_run_max_h=round(max(runs) / 3600, 1) if runs else 0.0,
        autonomy_median_min=round(statistics.median(spans) / 60, 1) if spans else 0.0,
        models=dict(s.models.most_common(4)),
    )


PERSONAL_RE = re.compile(r"体检|医院|挂号|癌|糖尿病|内分泌|肠胃|病|药|投资|理财|账户资产|股票|基金|保险|工资|房贷|租房|相亲|恋爱|"
                         r"\b(health|doctor|hospital|invest(ing|ment)?|portfolio|salary|mortgage|dating)\b", re.I)


def score(st: dict) -> float:
    o = st["orch"]
    orch = o.get("delegations", 0) + o.get("messages", 0) + o.get("schedules", 0) + o.get("plans", 0) + o.get("questions", 0)
    return round(min(st["human_turns"], 30) + 2 * min(orch, 25) + 2 * st["compactions"] + min(st["harness_turns"], 20) / 2
                 + min(st["active_h"], 12) + 3 * st["goals"], 1)


def proj_key(s: Session) -> str:
    return (s.cwd or "").rstrip("/") or "(unknown)"


def assign_aliases(sessions: list[Session], red: Redactor) -> dict[int, str]:
    amap = {}
    for s in sessions:
        red.alias("machine", s.machine, "m")
        red.alias("project", proj_key(s), "P")
        amap[id(s)] = red.alias("session", f"{s.source}:{s.sid}", "S")
    return amap


def local(dt: datetime, fmt="%Y-%m-%d %H:%M") -> str:
    return dt.astimezone().strftime(fmt)


def dur(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def _priv(args) -> Path | None:
    return Path(args.out) / "private" if getattr(args, "out", None) else None


def _redactor(args) -> Redactor:
    priv = _priv(args)
    return Redactor(Path(args.denylist) if args.denylist else None, aliases=priv / "aliases.json" if priv else None)


# ---------------------------------------------------------------- scan -----
def cmd_scan(args):
    red = _redactor(args)
    sessions, dropped = load_sessions(args)
    amap = assign_aliases(sessions, red)
    gap = timedelta(minutes=args.idle_gap)
    rows = []
    for s in sessions:
        st = session_stats(s, gap)
        first = next((e for e in s.events if e.kind in ("human", "command")), None)
        ftxt = (first.text if first.kind == "human" else f"{first.name} {first.text}") if first else ""
        rows.append(dict(alias=amap[id(s)], source=s.source, machine=red.aliases["machine"][s.machine],
                         project=red.aliases["project"][proj_key(s)], cwd=s.cwd, path=str(s.path), sid=s.sid,
                         title=s.title, score=score(st), first_prompt=one_line(red(ftxt), LIMITS["first"]), **st))
    if args.top:
        keep = {r["alias"] for r in sorted(rows, key=lambda r: -r["score"])[: args.top]}
        rows = [r for r in rows if r["alias"] in keep]
    priv = _priv(args)
    if priv:
        priv.mkdir(parents=True, exist_ok=True)
        (priv / "index.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        red.save()
    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return
    print(f"{len(rows)} sessions (idle gap {args.idle_gap}m)"
          + (" · left out: " + ", ".join(f"{v} {k}" for k, v in dropped.items()) if dropped else "") + "\n")
    print("S    start            act_h proj src  H  st  wake tools  ⤷   ✉   ⏰  sub ⟲ ◎ score  project · first prompt")
    for r in rows:
        o = r["orch"]
        print(f"{r['alias']:4} {local(datetime.fromisoformat(r['start'])):16} {r['active_h']:5.1f} {r['project']:4} "
              f"{r['source'][:4]:4} {r['human_turns']:2} {r['steers']:3} {r['harness_turns']:5} {r['tool_calls']:5} "
              f"{o.get('delegations', 0):3} {o.get('messages', 0):3} {o.get('schedules', 0):3} {r['subagents']:4} "
              f"{r['compactions']:1} {r['goals']:1} {r['score']:5.1f}  {'⚑personal? ' if r['personal'] else ''}{Path(r['cwd']).name or '?'} · {r['first_prompt'][:80]}")
    print(f"\nH human prompts · st typed while busy · wake harness-started turns · ⤷ delegations · ✉ agent messages · "
          f"⏰ cron/wakeups · sub subagent transcripts · ⟲ compactions · ◎ goals")
    print(f"projects: {len({r['project'] for r in rows})} · human prompts: {sum(r['human_turns'] for r in rows)} · "
          f"≈{sum(r['human_chars'] for r in rows) // 1000}k chars of human text")


# -------------------------------------------------------------- digest -----
HUMAN_SIDE = ("answer", "reject", "interrupt", "cmd")


def render_user(alias: str, s: Session, turns: list[Turn], red: Redactor, proj: str) -> str:
    L = [f"# {alias} · human side only · {proj} · {s.source} · {s.kind}",
         f"{local(s.start)} → {local(s.end)}" + live_note(s), ""]
    prev = None
    for t in turns:
        side = [e for e in t.body if e.kind in HUMAN_SIDE or (e.kind == "goal" and e.name == "set")]
        if t.trigger not in ("human", "command"):
            if side:
                L.append(f"## {t.label} · (inside a harness-started turn) · {local(t.ts)}")
                L += [human_side_line(e, red) for e in side] + [""]
            continue
        gap = f"+{dur((t.ts - prev).total_seconds())}" if prev else "start"
        prev = t.ts
        h = t.head
        tag = "`" + h.name + "` " if h.kind == "command" else ""
        flags = (" · typed while the agent was busy" if h.meta.get("steer") else "") \
            + (f" · sent ×{h.meta['repeats']}" if h.meta.get("repeats") else "") + (" · sent early, then in full" if h.meta.get("revised") else "")
        L += [f"## {t.label} · {local(t.ts)} ({gap}){flags}", (tag + red(clip(h.text, LIMITS["human"]))).strip() or "(empty)"]
        L += [human_side_line(e, red) for e in side] + [""]
    return "\n".join(L)


def human_side_line(e: Ev, red: Redactor) -> str:
    if e.kind == "answer":
        return f"\n  ↳ answered the agent's question: {red(one_line(e.text, LIMITS['qa']))}"
    if e.kind == "reject":
        return f"\n  ✋ rejected a {e.name or 'tool'} call" + (f": {red(one_line(e.text, LIMITS['qa']))}" if e.text else "")
    if e.kind == "interrupt":
        return "\n  ⛔ interrupted the agent"
    if e.kind == "cmd":
        return f"\n  ⌘ {e.name} {red(e.text)}".rstrip()
    return f"\n  ◎ set a goal: {red(one_line(e.text, LIMITS['qa']))}"


def live_note(s: Session) -> str:
    return " · still active when digested (snapshot)" if datetime.now(timezone.utc) - s.end < timedelta(minutes=30) else ""


def active_between(ivs, a: datetime, b: datetime) -> float:
    return sum(max(0.0, (min(y, b) - max(x, a)).total_seconds()) for x, y in ivs)


def render_dialog(alias: str, s: Session, turns: list[Turn], red: Redactor, proj: str, narration: bool,
                  gap: timedelta = timedelta(minutes=15)) -> str:
    ivs = active_intervals(s.stamps, gap)
    L = [f"# {alias} · dialogue (final responses; ordinary tool calls collapsed) · {proj} · {s.source} · {s.kind}",
         f"{local(s.start)} → {local(s.end)}{live_note(s)} · models: {', '.join(s.models) or '?'} · branch: {red(s.branch) or '-'}"]
    if s.subs:
        kinds = Counter(("teammate" if x.get("teammate") else x.get("kind", "subagent")) for x in s.subs)
        mates = sorted({red(x.get("name", "")) for x in s.subs if x.get("teammate") and x.get("name")})
        L.append(f"subagent transcripts: {len(s.subs)} (" + ", ".join(f"{k}×{v}" for k, v in kinds.most_common())
                 + ")" + (f" · teammates: {', '.join(mates[:20])}" if mates else ""))
    L.append("")
    for i, t in enumerate(turns):
        h = t.head
        when = local(t.ts)
        nxt = turns[i + 1] if i + 1 < len(turns) else None
        if t.trigger in ("human", "command"):
            steer = " (typed while the agent was busy)" if h.meta.get("steer") else ""
            L.append(f"## {t.label} · human{steer} · {when}")
            L.append(("`" + h.name + "` " if h.kind == "command" else "") + red(clip(h.text, LIMITS["human"])))
        elif t.trigger == "resume":
            L.append(f"## {t.label} · (session opens without a human prompt) · {when}")
        else:
            kind = t.trigger.split(":", 1)[1]
            who = f" from {red(h.meta['from'])}" if h.meta.get("from") else ""
            L.append(f"## {t.label} · harness: {WAKE_LABEL.get(kind, kind)}{who} · {when}")
            L.append("> " + red(one_line(h.text, LIMITS["wake"])))
        L.append("")
        tools = Counter(e.name for e in t.body if e.kind == "tool")
        n_orch = 0
        goal_checks = [e for e in t.body if e.kind == "goal" and e.name == "check"]
        for e in t.body:
            if e.kind == "orch":
                n_orch += 1
                L.append(f"{ORCH[e.name]} {e.name}: {red(e.text)}")
                if e.meta.get("prompt"):
                    L.append("   prompt » " + red(one_line(e.meta["prompt"], LIMITS["delegate"])))
                if e.meta.get("result"):
                    L.append("   result « " + red(one_line(e.meta["result"], LIMITS["result"])))
            elif e.kind == "compact":
                if e.name == "boundary":
                    L.append(f"⟲ compaction ({e.meta.get('trigger') or 'auto'}"
                             + (f", {int(e.meta['pre']) // 1000}k tokens before" if e.meta.get("pre") else "") + ")")
                elif e.text:
                    L.append("⟲ summary the harness carried forward: " + red(clip(compact_core(e.text), LIMITS["compact"])))
            elif e.kind == "answer":
                L.append("? human answered: " + red(one_line(e.text, LIMITS["qa"])))
            elif e.kind == "reject":
                L.append(f"✋ human rejected {e.name or 'a tool call'}" + (": " + red(one_line(e.text, LIMITS["qa"])) if e.text else ""))
            elif e.kind == "interrupt":
                L.append("⛔ interrupted by the human")
            elif e.kind == "cmd":
                L.append(f"⌘ {e.name} {red(e.text)}".rstrip())
            elif e.kind == "goal" and e.name != "check":
                L.append(f"◎ goal {e.name}: {red(one_line(e.text, LIMITS['qa']))}")
            elif e.kind == "apierr":
                L.append(f"⚠ api error {red(one_line(e.text, 100))}")
            elif e.kind == "narr" and narration:
                L.append("… " + red(one_line(e.text, LIMITS["narr"])))
        if goal_checks:
            g = goal_checks[-1]
            L.append(f"◎ goal check ×{len(goal_checks)}, last: {'met' if g.meta.get('met') else 'not met'} — {red(one_line(g.text, 200))}")
        if tools or n_orch:
            L.append(f"⚙ {sum(tools.values()) + n_orch} calls · " + " ".join(f"{k}×{v}" for k, v in tools.most_common(8))
                     + f" · active {dur(active_between(ivs, t.ts, t.end))} over {dur((t.end - t.ts).total_seconds())}")
        fin, status = t.final()
        absorbed = nxt is not None and nxt.head is not None and nxt.head.meta.get("steer")
        note = " _(no final yet: the agent kept working and the next prompt was typed while it was busy)_" if absorbed and status != "ok" \
            else {"unfinished": " _(turn ended without a clean final: interrupt, error, or early stop)_"}.get(status, "")
        L += ["", "**final**" + note + " " + (red(clip(fin, LIMITS["final"])) if fin else "_(no text)_"), ""]
    return "\n".join(L)


COMPACT_KEEP = re.compile(r"(?ms)^\s*(?:#+\s*)?(?:1\.\s*Primary Request and Intent|7\.\s*Pending Tasks|8\.\s*Current Work|9\.\s*Optional Next Step).*?(?=^\s*(?:#+\s*)?\d\.\s|\Z)")


def compact_core(text: str) -> str:
    """Keep the goal-bearing sections of a compaction summary."""
    parts = [m.group(0).strip() for m in COMPACT_KEEP.finditer(text)]
    return "\n".join(parts) if parts else text


def cmd_digest(args):
    out = Path(args.out)
    priv = out / "private"
    (priv / "digests").mkdir(parents=True, exist_ok=True)
    red = _redactor(args)
    sessions, _ = load_sessions(args)
    amap = assign_aliases(sessions, red)
    if args.sessions:
        want = {x.strip() for x in args.sessions.split(",")}
        sessions = [s for s in sessions if amap[id(s)] in want or any(s.sid.startswith(w) for w in want)]
    stream = []
    lo, hi = parse_when(args.since), parse_when(args.until)
    in_window = lambda ts: (not lo or ts >= lo) and (not hi or ts <= hi)  # noqa: E731
    for s in sessions:
        alias = amap[id(s)]
        proj = red.aliases["project"][proj_key(s)]
        turns = build_turns(s)
        (priv / "digests" / f"{alias}.user.md").write_text(render_user(alias, s, turns, red, proj))
        (priv / "digests" / f"{alias}.dialog.md").write_text(render_dialog(alias, s, turns, red, proj, args.narration,
                                                                             timedelta(minutes=args.idle_gap)))
        for t in turns:
            if t.trigger in ("human", "command") and in_window(t.ts):
                txt = (t.head.name + " " if t.head.kind == "command" else "") + t.head.text
                steer = " ↪" if t.head.meta.get("steer") else ""
                stream.append((t.ts, f"{local(t.ts)} · {alias}·{t.label}{steer} · {proj} — {red(one_line(txt, LIMITS['stream']))}"))
            for e in t.body:
                if e.kind == "answer" and in_window(e.ts):
                    stream.append((e.ts, f"{local(e.ts)} · {alias}·{t.label} ? · {proj} — answered: {red(one_line(e.text, 160))}"))
    stream.sort()
    (priv / "user-stream.md").write_text("# All human prompts, chronological (↪ = typed while that agent was busy; clipped — "
                                         "full text in digests/<S>.user.md)\n\n" + "\n".join(x for _, x in stream) + "\n")
    red.save()
    (out / ".gitignore").write_text("private/\nSTATE.md\n")
    sizes = sum(p.stat().st_size for p in (priv / "digests").glob("*.md"))
    print(f"digested {len(sessions)} sessions → {priv / 'digests'} ({sizes // 1000} kB) · {len(stream)} human prompts in user-stream.md")
    print("layer-1 redactions: " + (", ".join(f"{k}={v}" for k, v in sorted(red.hits.items())) or "none"))


# ------------------------------------------------------------ timeline -----
BARS = " ▁▂▃▄▅▆▇█"


def sweep(intervals: list[tuple[datetime, datetime]]):
    edges = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals])
    level, peak, peak_at, prev = 0, 0, None, None
    at_level: Counter = Counter()
    hourly: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    for t, d in edges:
        if prev is not None and level > 0 and t > prev:
            at_level[level] += (t - prev).total_seconds()
            h = prev.astimezone().replace(minute=0, second=0, microsecond=0)
            while h < t.astimezone():
                row = hourly[h.strftime("%Y-%m-%d")]
                row[h.hour] = max(row[h.hour], level)
                h += timedelta(hours=1)
        level += d
        prev = t
        if level > peak:
            peak, peak_at = level, t
    return peak, peak_at, at_level, hourly


def cmd_timeline(args):
    out = Path(args.out)
    priv = out / "private"
    priv.mkdir(parents=True, exist_ok=True)
    red = _redactor(args)
    sessions, _ = load_sessions(args)
    amap = assign_aliases(sessions, red)
    gap = timedelta(minutes=args.idle_gap)
    lo, hi = parse_when(args.since), parse_when(args.until)

    def clipped(v):
        res = []
        for a, b in v:
            a, b = (max(a, lo) if lo else a), (min(b, hi) if hi else b)
            if b > a:
                res.append((a, b))
        return res

    ivs = {amap[id(s)]: clipped(active_intervals(s.stamps, gap)) for s in sessions}
    subs = clipped([(x["start"], max(x["end"], x["start"] + timedelta(minutes=1))) for s in sessions for x in s.subs])
    peak, peak_at, at_level, hourly = sweep([iv for v in ivs.values() for iv in v])
    a_peak, a_peak_at, a_level, _ = sweep([iv for v in ivs.values() for iv in v] + subs)
    stats = {id(s): session_stats(s, gap) for s in sessions}
    prompts = sorted((e.ts, amap[id(s)]) for s in sessions for e in s.events
                     if e.kind in ("human", "command") and (not lo or e.ts >= lo) and (not hi or e.ts <= hi))
    switches = sum(1 for (_, a), (_, b) in zip(prompts, prompts[1:]) if a != b)
    union = sum(at_level.values()) / 3600
    spans = [stats[i]["autonomy_max_min"] for i in stats if stats[i]["human_turns"]]
    tot = lambda k: sum(stats[i]["orch"].get(k, 0) for i in stats)  # noqa: E731
    kpi = dict(
        sessions=len(sessions), projects=len({proj_key(s) for s in sessions}),
        peak_parallel=peak, peak_at=local(peak_at, "%Y-%m-%d %H:00") if peak_at else "-",
        mean_parallel=round(sum(k * v for k, v in at_level.items()) / max(sum(at_level.values()), 1), 2),
        peak_agents=a_peak, mean_agents=round(sum(k * v for k, v in a_level.items()) / max(sum(a_level.values()), 1), 2),
        active_hours=round(union, 1), session_hours=round(sum((b - a).total_seconds() for v in ivs.values() for a, b in v) / 3600, 1),
        human_prompts=len(prompts), steers=sum(stats[i]["steers"] for i in stats),
        prompts_per_hour=round(len(prompts) / union, 1) if union else 0,
        switches=switches, switches_per_hour=round(switches / union, 1) if union else 0,
        autonomy=round(statistics.median(spans), 1) if spans else 0,
        self_run=round(statistics.median([stats[i]["self_run_max_h"] for i in stats if stats[i]["human_turns"]] or [0]), 1),
        self_run_top=max([stats[i]["self_run_max_h"] for i in stats] or [0]),
        harness_turns=sum(stats[i]["harness_turns"] for i in stats), subagents=len(subs),
        delegations=tot("delegations"), messages=tot("messages"), schedules=tot("schedules"),
        compactions=sum(stats[i]["compactions"] for i in stats), goals=sum(stats[i]["goals"] for i in stats),
        interrupts=sum(stats[i]["interrupts"] for i in stats), unfinished=sum(stats[i]["unfinished_turns"] for i in stats),
        hours_at_level={k: round(v / 3600, 1) for k, v in sorted(at_level.items())},
    )
    (priv / "timeline.json").write_text(json.dumps(dict(
        kpi=kpi, hourly=hourly, per_session={amap[id(s)]: {k: stats[id(s)][k] for k in ("kind", "active_h", "human_turns",
                                             "steers", "harness_turns", "subagents", "teammates", "compactions", "goals",
                                             "autonomy_max_min", "self_run_max_h", "autonomy_median_min", "orch", "wakes")} for s in sessions},
        intervals={k: [(a.isoformat(), b.isoformat()) for a, b in v] for k, v in ivs.items()}), indent=1, ensure_ascii=False))
    names = [("sessions", "sessions in scope"), ("projects", "projects"), ("peak_parallel", "peak parallel sessions"),
             ("peak_at", "peak at"), ("mean_parallel", "mean parallel sessions while any is active"),
             ("peak_agents", "peak parallel agents (sessions + subagents)"), ("mean_agents", "mean parallel agents while active"),
             ("active_hours", "hours with ≥1 session active"), ("session_hours", "sum of session-active hours"),
             ("human_prompts", "human prompts"), ("steers", "…of them typed while the agent was busy"),
             ("prompts_per_hour", "human prompts per active hour"), ("switches", "switches between sessions"),
             ("switches_per_hour", "switches per active hour"), ("autonomy", "median of each session's longest unattended stretch (active min between human prompts)"),
             ("self_run", "median of each session's longest self-sustained run after a prompt (wall h)"),
             ("self_run_top", "longest self-sustained run after a prompt (wall h)"),
             ("harness_turns", "turns started by the harness, not the human"), ("subagents", "subagent / teammate transcripts"),
             ("delegations", "delegation calls"), ("messages", "agent-to-agent messages"), ("schedules", "cron / wakeup calls"),
             ("compactions", "compactions"), ("goals", "goals set"), ("interrupts", "human interrupts"),
             ("unfinished", "human turns without a clean final")]
    L = ["# Concurrency timeline", "", f"Idle gaps over {args.idle_gap} min split a session's activity. Local time.", "",
         "| metric | value |", "|---|---|"] + [f"| {label} | {kpi[k]} |" for k, label in names]
    L += ["", "Hours at each level of session parallelism: " + ", ".join(f"{k}→{v}h" for k, v in kpi["hours_at_level"].items()), "",
          "## Heat strip — peak concurrent sessions within each hour (glyph height; table view below)", "", "```",
          "date         " + "".join(f"{h:<3}" for h in range(0, 24, 3)).rstrip()]
    for day in sorted(hourly):
        L.append(f"{day}   " + "".join(BARS[min(c, 8)] for c in hourly[day]) + f"   max {max(hourly[day])}")
    L += ["```", "", "<details><summary>table view</summary>", "", "| date | " + " | ".join(f"{h:02d}" for h in range(24)) + " |",
          "|---|" + "---|" * 24] + [f"| {d} | " + " | ".join(str(c) for c in hourly[d]) + " |" for d in sorted(hourly)]
    L += ["", "</details>", ""]
    top = sorted(sessions, key=lambda s: -stats[id(s)]["active_h"])[: args.gantt_top]
    L += ["## Gantt — active intervals of the busiest sessions", "", "```mermaid", "---", "displayMode: compact", "---", "gantt",
          "    dateFormat YYYY-MM-DD HH:mm", "    axisFormat %m-%d %Hh"]
    for s in sorted(top, key=lambda s: s.start):
        a = amap[id(s)]
        bars = [(x, y) for x, y in ivs[a] if (y - x) >= timedelta(minutes=args.min_bar)]
        if bars:
            L.append(f"    section {a} {red.aliases['project'][proj_key(s)]}")
            L += [f"    {a} : {local(x)}, {local(y)}" for x, y in bars]
    L += ["```", ""]
    if len(sessions) > len(top):
        L.append(f"{len(sessions) - len(top)} lighter sessions are not drawn (they are in the numbers above).")
    (priv / "timeline.md").write_text("\n".join(L) + "\n")
    red.save()
    print("\n".join(L[: 6 + len(names) + 2]))
    print(f"→ {priv / 'timeline.md'}")


# ------------------------------------------------------------- suggest -----
COMMON = set("""API CLI GPU CPU HTTP HTTPS JSON YAML TOML HTML CSS SQL URL URI SSH SDK LLM RAG MCP PR CI CD OK TODO README
MD PDF PNG SVG AI ML NLP RL SFT DPO PPO GRPO RLHF LORA QLORA FP8 FP16 BF16 INT8 KV MOE TPU CUDA NCCL OOM ASAP FYI IO UI UX
ID IDS UTC GMT AWS GCP ENV PATH HOME USER JWT OAUTH SSO VPN DNS TCP UDP IP REST RPC GRPC SSE TTL LRU FIFO CRUD ORM DB
MAX MIN AVG TOP NEW OLD DONE WIP BUG FIX ERROR WARN INFO DEBUG NOTE TBD PASS FAIL YES NO GPT CC URL UUID HEX PATH HOST
BLOB SECRET EMAIL PHONE REDACTED IMAGE""".split())
CAND_RES = [
    ("CamelCase", re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")),
    ("ACRONYM", re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")),
    ("kebab/snake", re.compile(r"\b[a-z][a-z0-9]+(?:[-_][a-z0-9]+)+\b")),
    ("alnum", re.compile(r"\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{4,}\b")),
    ("CJK in quotes", re.compile(r"[「“\"]([一-鿿]{2,8})[」”\"]")),
]


def cmd_suggest(args):
    priv = Path(args.out) / "private"
    texts = [p.read_text() for p in sorted((priv / "digests").glob("*.user.md"))]
    if args.dialog:
        texts += [p.read_text() for p in sorted((priv / "digests").glob("*.dialog.md"))]
    blob = "\n".join(texts)
    found: dict[str, Counter] = defaultdict(Counter)
    for cls, pat in CAND_RES:
        for m in pat.finditer(blob):
            w = m.group(1) if pat.groups else m.group(0)
            if w.upper() in COMMON or re.fullmatch(r"[STP]\d+(\.\d+)?|m\d+|v?\d+(\.\d+)*[a-z]?|[a-z]+\d?", w):
                continue
            found[cls][w] += 1
    import difflib
    known = [pat.pattern for pat, _ in load_list(CONFIG_DIR / "denylist.txt") + load_list(priv / "denylist.txt")]
    known = [re.sub(r"\(\?<!\[A-Za-z0-9\]\)|\(\?!\[A-Za-z0-9\]\)|\\", "", k) for k in known if not k.startswith("re:")]
    aliases = json.loads((priv / "aliases.json").read_text()) if (priv / "aliases.json").exists() else {}
    known += [Path(k).name for k in aliases.get("project", {}) if len(Path(k).name) >= 5]
    words = {w for w in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{4,}", blob)}
    near = sorted({w for w in words for k in known if w.lower() != k.lower() and len(k) >= 5
                   and difflib.SequenceMatcher(None, w.lower(), k.lower()).ratio() >= 0.84})
    if near:
        found["near-miss variants of known names"] = Counter({w: blob.count(w) for w in near})
    print("Terms still visible after layer-1 redaction. Mark the sensitive ones and append them to")
    print(f"{CONFIG_DIR / 'denylist.txt'} (or {priv / 'denylist.txt'} for this run only), one per line: `term => [ALIAS]`.")
    print("This list itself is sensitive: keep it out of chat summaries and public files.\n")
    for cls, cnt in found.items():
        items = [f"{w}×{n}" for w, n in cnt.most_common(args.limit) if n >= args.min_count]
        if items:
            print(f"[{cls}] " + ", ".join(items) + "\n")


# ----------------------------------------------------------- leakcheck -----
BLOCKING = {"pem", "token", "jwt", "bearer", "email", "ip", "phone", "abs-path", "host", "denylist", "real-name", "high-entropy"}


def cmd_leakcheck(args):
    root = Path(args.path)
    aliases = Path(args.aliases) if args.aliases else (root.parent / "private" / "aliases.json")
    findings = leakcheck(root, Path(args.denylist) if args.denylist else None, aliases)
    block = [f for f in findings if f[2] in BLOCKING]
    review = [f for f in findings if f[2] not in BLOCKING]
    for f, n, cls, hit in block + review:
        print(f"{'BLOCK ' if cls in BLOCKING else 'review'}  {f}:{n}  {cls}  {hit}")
    print(f"\n{len(block)} blocking, {len(review)} to review · {root}")
    sys.exit(1 if block else 0)


# ----------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def scope(p):
        p.add_argument("--src", action="append", default=[], help="KIND[@MACHINE]:PATH (claude|codex|grok); repeatable")
        p.add_argument("--since", help="e.g. 7d, 48h, 2026-09-01")
        p.add_argument("--until")
        p.add_argument("--project", action="append", default=[], help="substring of the session cwd; repeatable")
        p.add_argument("--exclude", action="append", default=[], help="substring of cwd to leave out; repeatable")
        p.add_argument("--min-human", type=int, default=1, help="minimum human prompts per session (default 1)")
        p.add_argument("--include-sdk", action="store_true", help="also include programmatic runs (Agent SDK, codex exec)")
        p.add_argument("--idle-gap", type=int, default=15, help="minutes of silence that split activity (default 15)")
        p.add_argument("--denylist", help=f"default {CONFIG_DIR / 'denylist.txt'} (+ <out>/private/denylist.txt)")

    p = sub.add_parser("scan", help="list sessions in scope")
    scope(p)
    p.add_argument("--out")
    p.add_argument("--top", type=int, default=0, help="keep the N highest-scoring sessions")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("digest", help="write declassified digests")
    scope(p)
    p.add_argument("--out", required=True)
    p.add_argument("--sessions", help="comma list of aliases (S03) or session-id prefixes; default: all in scope")
    p.add_argument("--narration", action="store_true", help="also keep short intermediate assistant texts")
    p.set_defaults(fn=cmd_digest)

    p = sub.add_parser("timeline", help="concurrency analysis")
    scope(p)
    p.add_argument("--out", required=True)
    p.add_argument("--gantt-top", type=int, default=20)
    p.add_argument("--min-bar", type=int, default=5, help="minutes; shorter intervals are not drawn in the gantt")
    p.set_defaults(fn=cmd_timeline)

    p = sub.add_parser("suggest", help="candidate denylist terms")
    p.add_argument("--out", required=True)
    p.add_argument("--dialog", action="store_true", help="also scan dialog digests, not only human prompts")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--min-count", type=int, default=2)
    p.set_defaults(fn=cmd_suggest)

    p = sub.add_parser("leakcheck", help="block-or-pass check of a directory before publishing")
    p.add_argument("path")
    p.add_argument("--denylist")
    p.add_argument("--aliases")
    p.set_defaults(fn=cmd_leakcheck)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
