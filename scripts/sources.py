"""Transcript adapters: Claude Code and Codex rollouts -> Session(events).

Event kinds
  human    genuine prompt typed by the operator (meta.steer: typed while the agent was busy)
  command  slash command with its args (starts a turn)
  cmd      local slash command with no model reply (inline)
  answer   operator's answer to a question the agent asked
  reject   operator rejected a tool call
  interrupt operator interrupted the agent
  wake     harness-initiated turn: notify | teammsg | peer | cron | goal | automation
  compact  compaction boundary or summary
  goal     goal set / goal check
  narr     assistant text (meta: mid, stop, final)
  apierr   synthetic API-error message
  tool     ordinary tool call (collapsed to counts)
  orch     orchestration tool call (kept, short)
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ORCH = {
    # delegation
    "Agent": "⤷", "Task": "⤷", "spawn_agent": "⤷", "followup_task": "⤷", "spawn_task": "⤷", "Workflow": "⤷",
    # messages between agents and sessions
    "SendMessage": "✉", "send_message": "✉", "send_input": "✉", "SubagentHandback": "✉", "send_message_to_thread": "✉",
    # supervising background work
    "TaskOutput": "⊙", "TaskStop": "⊙", "ListAgents": "⊙", "list_agents": "⊙", "wait_agent": "⊙", "interrupt_agent": "⊙",
    "Monitor": "⊙", "wait_threads": "⊙", "list_threads": "⊙", "read_thread": "⊙",
    # time
    "CronCreate": "⏰", "CronDelete": "⏰", "CronList": "⏰", "ScheduleWakeup": "⏰", "RemoteTrigger": "⏰",
    "automation_update": "⏰", "sleep": "⏰",
    # plans and task lists
    "TaskCreate": "☰", "TaskUpdate": "☰", "TodoWrite": "☰", "update_plan": "☰", "EnterPlanMode": "◇", "ExitPlanMode": "◇",
    # the channel to the human
    "AskUserQuestion": "?", "request_user_input_async": "?", "PushNotification": "⇪", "SendUserFile": "⇪",
    # loading capability / isolation
    "Skill": "✎", "EnterWorktree": "⎇", "ExitWorktree": "⎇",
    # grok build
    "spawn_subagent": "⤷", "workflow": "⤷", "scheduler_create": "⏰", "scheduler_delete": "⏰", "scheduler_list": "⏰",
    "todo_write": "☰", "ask_user_question": "?", "monitor": "⊙", "get_command_or_subagent_output": "⊙",
    "kill_command_or_subagent": "⊙", "wait_commands_or_subagents": "⊙",
}
GLYPH_STAT = {"⤷": "delegations", "✉": "messages", "⊙": "supervision", "⏰": "schedules", "☰": "tasks", "◇": "plans",
              "?": "questions", "⇪": "pings", "✎": "skills", "⎇": "worktrees"}

TS_RE = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')
ORD_RE = re.compile(r'"ordinal"\s*:\s*(\d+)')


@dataclass
class Ev:
    ts: datetime
    kind: str
    text: str = ""
    name: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Session:
    source: str
    machine: str
    path: Path
    sid: str
    kind: str = "interactive"          # interactive | programmatic | automation
    cwd: str = ""
    branch: str = ""
    version: str = ""
    title: str = ""
    thread: str = ""                   # codex thread id
    parent_thread: str = ""
    agent_name: str = ""
    models: Counter = field(default_factory=Counter)
    events: list = field(default_factory=list)
    stamps: list = field(default_factory=list)
    subs: list = field(default_factory=list)   # dict(kind, name, teammate, start, end)

    @property
    def start(self) -> datetime:
        return self.stamps[0]

    @property
    def end(self) -> datetime:
        return self.stamps[-1]


def ts_of(s) -> datetime | None:
    if not s:
        return None
    if isinstance(s, (int, float)):
        return datetime.fromtimestamp(s / 1000 if s > 1e11 else s, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def one_line(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _lines(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield line


def _load(line: str):
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def first_last_ts(path: Path) -> tuple[datetime | None, datetime | None]:
    first = last = None
    try:
        with path.open("rb") as fh:
            for raw in fh:
                m = TS_RE.search(raw.decode("utf-8", "replace"))
                if m:
                    first = ts_of(m.group(1))
                    break
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 262144))
            for raw in reversed(fh.read().decode("utf-8", "replace").splitlines()):
                m = TS_RE.search(raw)
                if m:
                    last = ts_of(m.group(1))
                    break
    except OSError:
        pass
    return first, last


def orch_summary(name: str, inp: dict) -> str:
    def g(*keys):
        for k in keys:
            v = inp.get(k)
            if v:
                v = str(v)
                return "(encrypted)" if v.startswith("gAAAAA") and " " not in v[:200] else v
        return ""
    if name == "spawn_subagent":
        flags = ",".join(x for x in (g("subagent_type"), "bg" if inp.get("background") else "", g("model"), g("capability_mode")) if x)
        return f'{g("description")} [{flags}]'
    if name == "scheduler_create":
        return f'{g("interval")}: {one_line(g("prompt"), 160)}'
    if name == "todo_write":
        return f'{len(inp.get("todos") or [])} items'
    if name in ("Agent", "Task", "spawn_agent", "spawn_task"):
        flags = ",".join(x for x in (g("subagent_type"), "bg" if inp.get("run_in_background") else "", g("team_name") and "team",
                                     g("isolation"), g("model"), g("fork_turns") and f"fork={g('fork_turns')}") if x)
        return f'{g("name", "task_name", "description", "title")} [{flags}]'
    if name == "Workflow":
        m = re.search(r"description:\s*['\"]([^'\"]+)", g("script"))
        return one_line(g("description", "name", "scriptPath") or (m.group(1) if m else ""), 140)
    if name in ("SendMessage", "send_message", "send_input", "followup_task", "send_message_to_thread"):
        target = re.sub(r"^/root/", "", g("to", "target", "thread_id"))
        return f'to={target}: {one_line(g("summary", "message", "content", "input"), 160)}'
    if name == "automation_update":
        return f'{g("mode")} {g("kind")} {g("rrule")}: {one_line(g("name") or g("prompt"), 140)}'.strip()
    if name == "CronCreate":
        return f'{g("cron", "schedule")}{" recurring" if inp.get("recurring") else ""}: {one_line(g("prompt"), 160)}'
    if name == "ScheduleWakeup":
        return f'{g("delaySeconds")}s — {one_line(g("reason"), 120)}'
    if name == "Monitor":
        return one_line(g("description", "command"), 120)
    if name == "Skill":
        return f'{g("skill")} {one_line(g("args"), 100)}'.strip()
    if name == "TodoWrite":
        return f'{len(inp.get("todos") or [])} items'
    if name in ("TaskCreate", "TaskUpdate"):
        return one_line(g("subject", "status", "taskId"), 100)
    if name == "update_plan":
        return f'{len(inp.get("plan") or [])} steps'
    if name in ("AskUserQuestion", "request_user_input_async"):
        qs = inp.get("questions") or []
        if qs and isinstance(qs, list):
            return " | ".join(one_line(q.get("question") or q.get("title") or q.get("header", ""), 120) for q in qs if isinstance(q, dict))
        return one_line(g("question", "prompt", "message"), 160)
    if name == "ExitPlanMode":
        return one_line(g("plan"), 300)
    return one_line(json.dumps(inp, ensure_ascii=False), 140)


# ------------------------------------------------------------ claude code ---
CLAUDE_REJECT = ("<task-notification>", "<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>",
                 "[Request interrupted by user", "Another Claude session sent a message:", "<teammate-message",
                 "<\\teammate-message", "<agent-message", "<cross-session-message", "<system-reminder>",
                 "This session is being continued from a previous conversation",
                 "Caveat: The messages below were generated by the user", "Base directory for this skill:")
TURN_ORIGIN_WAKE = {"task_notification": "notify", "scheduled": "cron", "peer": "peer", "auto_continuation": "goal"}
SR_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
CMD_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
CMD_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
TAG_RE = re.compile(r"<(status|summary|result|event)>(.*?)</\1>", re.S)
ATTR_RE = re.compile(r'(teammate_id|summary|from-name|from|name)="([^"]*)"')
REJECT_MARK = "The user doesn't want to proceed with this tool use"
# Harness-control commands: inline markers, not turns.
TRIVIAL_CMDS = {"/model", "/effort", "/login", "/logout", "/resume", "/status", "/clear", "/compact", "/config", "/cost",
                "/usage", "/help", "/exit", "/permissions", "/mcp", "/agents", "/hooks", "/memory", "/context", "/rewind",
                "/fast", "/theme", "/vim", "/ide", "/doctor", "/release-notes", "/upgrade", "/add-dir", "/bashes", "/export",
                "/statusline", "/output-style", "/sandbox", "/plugin", "/skills", "/todos", "/tasks", "/privacy-settings",
                "/feedback", "/bug", "/rename", "/copy", "/terminal-setup", "/remote-control", "/stats", "/btw"}


def _blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text(blocks) -> str:
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def _result_text(block) -> str:
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return c if isinstance(c, str) else ""


def notification_text(text: str) -> str:
    parts = []
    for chunk in text.split("<task-notification>")[1:]:
        tags = dict(TAG_RE.findall(chunk))
        parts.append(f'[{tags.get("status", "event")}] {one_line(tags.get("summary") or tags.get("event", ""), 160)}'
                     + (f' — {tags["result"].strip()}' if tags.get("result") else ""))
    return "\n".join(parts) or text


def message_text(text: str) -> tuple[str, str]:
    """'Another Claude session sent a message: <teammate-message …>' -> (sender, text)."""
    body = text.split("sent a message:", 1)[-1].strip()
    attrs = dict(ATTR_RE.findall(body[:400]))
    sender = attrs.get("teammate_id") or attrs.get("from-name") or attrs.get("name") or attrs.get("from") or "?"
    inner = re.sub(r"^<[^>]+>", "", body).rsplit("</", 1)[0].strip()
    if inner.startswith("{") and '"result"' in inner:
        try:
            inner = json.loads(inner).get("result") or inner
        except json.JSONDecodeError:
            pass
    summary = attrs.get("summary", "")
    return sender, (summary + " — " if summary else "") + inner


def parse_claude(path: Path, machine: str) -> Session | None:
    stem = path.stem
    s = Session(source="claude-code", machine=machine, path=path, sid=stem)
    seen: set[str] = set()
    spawned: set[str] = set()          # names this session gave its own subagents / teammates
    pending: dict[str, Ev] = {}
    last_steer: dict[str, datetime] = {}
    sid_tag = f'"sessionId":"{stem}"'
    for line in _lines(path):
        # fast path: plain tool output we only need the time of
        if '"tool_result"' in line and REJECT_MARK not in line and not any(k in line for k in pending):
            if sid_tag in line.replace(" ", ""):
                m = TS_RE.search(line)
                t = ts_of(m.group(1)) if m else None
                if t:
                    s.stamps.append(t)
            continue
        rec = _load(line)
        if not isinstance(rec, dict):
            continue
        rtype = rec.get("type")
        if rtype in ("ai-title", "custom-title"):
            s.title = rec.get("customTitle") or s.title or rec.get("aiTitle", "")
            continue
        if rec.get("sessionId") not in (None, stem):
            continue                                    # history inherited from a resumed/forked parent
        uid = rec.get("uuid")
        if uid:
            if uid in seen:
                continue
            seen.add(uid)
        t = ts_of(rec.get("timestamp"))
        if t is None or rec.get("isSidechain"):
            continue
        s.stamps.append(t)
        s.cwd = s.cwd or rec.get("cwd", "")
        s.branch = s.branch or rec.get("gitBranch", "")
        s.version = rec.get("version") or s.version
        if rec.get("entrypoint") == "sdk-cli":
            s.kind = "programmatic"
        if rtype == "system":
            st = rec.get("subtype")
            if st == "compact_boundary":
                cm = rec.get("compactMetadata") or {}
                s.events.append(Ev(t, "compact", "", "boundary", {"trigger": cm.get("trigger", ""), "pre": cm.get("preTokens")}))
            elif st == "scheduled_task_fire":
                loop = "loop" in (str(rec.get("cronKind", "")) + str(rec.get("taskKind", "")))
                s.events.append(Ev(t, "wake", rec.get("prompt") or rec.get("content", ""), "loop" if loop else "cron",
                                   {"cron": rec.get("cron", "")}))
            elif st == "local_command":
                c = rec.get("content", "")
                m = CMD_NAME_RE.search(c)
                if m:
                    a = CMD_ARGS_RE.search(c)
                    s.events.append(Ev(t, "cmd", a.group(1).strip() if a else "", m.group(1).strip()))
            elif st == "api_error":
                s.events.append(Ev(t, "apierr", one_line(str(rec.get("content", "")), 120)))
            continue
        if rtype == "attachment":
            a = rec.get("attachment") or {}
            at = a.get("type")
            if at == "queued_command" and a.get("commandMode") == "prompt" and not a.get("isMeta") \
                    and (a.get("origin") or {}).get("kind", "human") == "human":
                p = a.get("prompt")
                txt = p if isinstance(p, str) else _text(_blocks(p))
                txt = SR_RE.sub("", txt or "").strip()
                if txt and not txt.startswith(CLAUDE_REJECT):
                    key = txt[:200]
                    if key not in last_steer or (t - last_steer[key]).total_seconds() > 600:
                        last_steer[key] = t
                        s.events.append(Ev(t, "human", txt, "", {"steer": True}))
            elif at == "goal_status":
                s.events.append(Ev(t, "goal", a.get("reason") or a.get("condition", ""), "check",
                                   {"met": a.get("met"), "condition": a.get("condition", "")}))
            elif at == "plan_mode_exit":
                s.events.append(Ev(t, "orch", "plan mode exited", "ExitPlanMode"))
            continue
        msg = rec.get("message") or {}
        if rtype == "user":
            blocks = _blocks(msg.get("content"))
            results = [b for b in blocks if b.get("type") == "tool_result"]
            if results or rec.get("toolUseResult") is not None:
                tur = rec.get("toolUseResult")
                for b in results:
                    tid = b.get("tool_use_id", "")
                    txt = _result_text(b)
                    ev = pending.pop(tid, None)
                    if REJECT_MARK in txt:
                        fb = txt.split("the user said:", 1)[1].strip() if "the user said:" in txt else ""
                        s.events.append(Ev(t, "reject", fb, ev.name if ev else ""))
                        continue
                    if not ev:
                        continue
                    if ev.name == "AskUserQuestion":
                        ans = (tur or {}).get("answers") if isinstance(tur, dict) else None
                        s.events.append(Ev(t, "answer", "; ".join(f"{q} → {a}" for q, a in ans.items()) if isinstance(ans, dict) else txt,
                                           "AskUserQuestion"))
                    elif ev.name in ("Agent", "Task"):
                        status = tur.get("status") if isinstance(tur, dict) else ""
                        ev.meta["status"] = status
                        if status == "completed":
                            ev.meta["result"] = txt
                continue
            if rec.get("isCompactSummary"):
                s.events.append(Ev(t, "compact", _text(blocks), "summary"))
                continue
            text = SR_RE.sub("", _text(blocks)).strip()
            n_img = sum(1 for b in blocks if b.get("type") == "image")
            origin = (rec.get("origin") or {}).get("kind")
            torigin = rec.get("turnOrigin")
            if origin == "task-notification" or text.startswith("<task-notification>"):
                s.events.append(Ev(t, "wake", notification_text(text), "notify"))
                continue
            if text.startswith("Another Claude session sent a message:") or origin == "peer":
                who, body = message_text(text)
                own = "teammate-message" in text[:200] or "[Subagent hand-back]" in text[:400] \
                    or who in spawned or (rec.get("origin") or {}).get("senderTaskId")
                kind = "teammsg" if own else "peer"
                s.events.append(Ev(t, "wake", body, kind, {"from": who}))
                continue
            if rec.get("isMeta"):
                if torigin == "auto_continuation" or text.startswith(("Stop hook feedback", "Goal check-in")):
                    s.events.append(Ev(t, "wake", text, "goal"))
                elif text.startswith("A session-scoped Stop hook is now active with condition") and not any(
                        e.kind == "goal" and e.name == "set" and (t - e.ts).total_seconds() < 120 for e in s.events[-20:]):
                    m = re.search(r'condition:\s*"(.*?)"(?:\s|$)', text, re.S)
                    s.events.append(Ev(t, "goal", m.group(1) if m else text.split("condition:", 1)[-1][:400], "set"))
                continue
            if torigin in TURN_ORIGIN_WAKE:
                if torigin != "scheduled":           # cron fires are taken from system/scheduled_task_fire
                    s.events.append(Ev(t, "wake", text, TURN_ORIGIN_WAKE[torigin]))
                continue
            if origin not in (None, "human"):
                continue
            if text.endswith("Please continue from where you left off.") and len(text) < 240:
                s.events.append(Ev(t, "wake", text, "resume"))
                continue
            if text.startswith("[Request interrupted by user"):
                if not rec.get("interruptedByShutdown"):
                    s.events.append(Ev(t, "interrupt"))
                continue
            if text.startswith(("<command-name>", "<command-message>")) or CMD_NAME_RE.search(text[:300] or ""):
                m = CMD_NAME_RE.search(text)
                a = CMD_ARGS_RE.search(text)
                name, args = (m.group(1).strip() if m else "?"), (a.group(1).strip() if a else "")
                s.events.append(Ev(t, "cmd" if name in TRIVIAL_CMDS else "command", args, name))
                if name == "/goal" and args and args != "clear":
                    s.events.append(Ev(t, "goal", args, "set"))
                continue
            if text.startswith(CLAUDE_REJECT):
                continue
            if text or n_img:
                s.events.append(Ev(t, "human", text + (" [image]" * n_img if n_img else "")))
            continue
        if rtype == "assistant":
            model = msg.get("model")
            if model == "<synthetic>" or rec.get("isApiErrorMessage"):
                err = rec.get("error")
                txt = err if isinstance(err, str) else _text(_blocks(msg.get("content")))[:120]
                if txt.strip() != "No response requested.":
                    s.events.append(Ev(t, "apierr", txt))
                continue
            if model:
                s.models[model] += 1
            mid, stop = msg.get("id") or uid, msg.get("stop_reason")
            for b in _blocks(msg.get("content")):
                bt = b.get("type")
                if bt == "text" and b.get("text", "").strip():
                    s.events.append(Ev(t, "narr", b["text"], "", {"mid": mid, "stop": stop}))
                elif bt == "tool_use":
                    name, inp = b.get("name", "?"), b.get("input") or {}
                    bare = name.split("__")[-1]
                    if name in ("Agent", "Task") and (inp.get("name") or inp.get("description")):
                        spawned.add(str(inp.get("name") or inp.get("description")))
                    if name in ORCH or bare in ORCH:
                        key = name if name in ORCH else bare
                        ev = Ev(t, "orch", orch_summary(key, inp), key,
                                {"prompt": inp.get("prompt", "") if key in ("Agent", "Task") else ""})
                        pending[b.get("id", "")] = ev
                    else:
                        ev = Ev(t, "tool", "", name)
                    s.events.append(ev)
    if not s.stamps:
        return None
    s.stamps.sort()
    sub_root = path.with_suffix("") / "subagents"
    if sub_root.is_dir():
        for f in sub_root.rglob("agent-*.jsonl"):
            a, b = first_last_ts(f)
            if not a:
                continue
            meta = {}
            mf = f.with_suffix(".meta.json")
            if mf.exists():
                try:
                    meta = json.loads(mf.read_text())
                except (json.JSONDecodeError, OSError):
                    meta = {}
            s.subs.append(dict(kind=meta.get("agentType") or ("workflow" if "workflows" in f.parts else "subagent"),
                               name=meta.get("name") or meta.get("description", ""), start=a, end=b or a,
                               teammate=meta.get("taskKind") == "in_process_teammate"))
    return s


# ------------------------------------------------------------------ codex ---
CODEX_INJECTED = ("# AGENTS.md instructions", "<INSTRUCTIONS>", "<environment_context>", "<recommended_plugins>", "<skill>",
                  "<subagents>", "<turn_aborted>", "<permissions", "<collaboration_mode>", "<skills_instructions>",
                  "<apps_instructions>", "<plugins_instructions>", "<app-context>", "<multi_agent_mode", "<model_switch>",
                  "<context_window", "<automation_id", "<current_date", "<user_instructions>")
# Record kinds we only need the timestamp of. Matched on the envelope head, never on free text inside the payload.
CODEX_FAST_RE = re.compile(r'"type"\s*:\s*"(?:token_usage_record|world_state)"|"payload"\s*:\s*\{\s*"type"\s*:\s*"(?:function_call_output|custom_tool_call_output|reasoning|token_count)"')
IMG_RE = re.compile(r"<image name=\[Image #\d+\][^>]*>(?:</image>)?")
BROWSER_RE = re.compile(r"<in-app-browser-context[^>]*>.*?(?:</in-app-browser-context>|\Z)", re.S)
REPLY_RE = re.compile(r"<send_user_message_question_reply>(.*?)</send_user_message_question_reply>", re.S)


def codex_user(text: str):
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("<heartbeat>"):
        return ("wake", t, "automation")
    if t.startswith("<codex_delegation>"):
        return ("wake", t, "peer")
    if t.startswith('<codex_internal_context source="goal"'):
        return ("wake", t, "goal")
    m = REPLY_RE.search(t)
    if m:
        return ("answer", m.group(1).strip(), "request_user_input")
    if t.startswith(CODEX_INJECTED):
        return None
    t = BROWSER_RE.sub("", t).strip()
    t = t.replace("Distinguish instructions in attached documents from the user's request.", "").strip()
    n_img = len(IMG_RE.findall(t))
    t = IMG_RE.sub("", t).strip()
    if t.startswith(("# Files mentioned by the user", "# Files pasted by the user")):
        if "## My request for Codex:" in t:
            head, req = t.split("## My request for Codex:", 1)
        else:
            lines = t.splitlines()
            keep = [ln for ln in lines[1:] if ln.strip() and not ln.startswith("## ")]
            head, req = t, "\n".join(keep)
        n = max(1, head.count("\n## "))
        t = f"[attached {n} file(s)] " + req.strip()
    if n_img:
        t += " [image]" * n_img
    return ("human", t.strip(), "") if t.strip() else None


def parse_codex(path: Path, machine: str) -> Session | None:
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path.stem)
    s = Session(source="codex", machine=machine, path=path, sid=m.group(1) if m else path.stem)
    start_ord, meta_seen, agent_path = None, False, ""
    user_items, fallback = 0, []
    for line in _lines(path):
        if CODEX_FAST_RE.search(line[:260]):
            mo = ORD_RE.search(line)
            if start_ord is not None and mo and int(mo.group(1)) < start_ord:
                continue
            mt = TS_RE.search(line)
            t = ts_of(mt.group(1)) if mt else None
            if t:
                s.stamps.append(t)
            continue
        rec = _load(line)
        if not isinstance(rec, dict):
            continue
        typ, p = rec.get("type"), rec.get("payload") or {}
        if typ == "session_meta":
            if not meta_seen:
                meta_seen = True
                s.thread = p.get("id") or p.get("session_id") or s.sid
                s.cwd = p.get("cwd", "")
                s.version = p.get("cli_version", "")
                s.branch = ((p.get("git") or {}).get("branch")) or ""
                src = p.get("source")
                spawn = (src.get("subagent") or {}).get("thread_spawn") if isinstance(src, dict) else None
                s.parent_thread = (spawn or {}).get("parent_thread_id") or p.get("parent_thread_id") or ""
                s.agent_name = (spawn or {}).get("agent_nickname") or (spawn or {}).get("agent_role") or ""
                agent_path = (spawn or {}).get("agent_path") or p.get("agent_path") or ""
                start_ord = p.get("subagent_history_start_ordinal")
                if src == "exec" or p.get("originator") == "codex_exec":
                    s.kind = "programmatic"
                elif p.get("thread_source") == "automation":
                    s.kind = "automation"
            continue
        if start_ord is not None and isinstance(rec.get("ordinal"), int) and rec["ordinal"] < start_ord:
            continue
        t = ts_of(rec.get("timestamp"))
        if t is None:
            continue
        s.stamps.append(t)
        if typ == "turn_context":
            if p.get("model"):
                s.models[p["model"]] += 1
            s.cwd = s.cwd or p.get("cwd", "")
        elif typ == "compacted":
            s.events.append(Ev(t, "compact", "", "boundary"))
        elif typ == "event_msg":
            et = p.get("type")
            if et == "item_completed":
                item = p.get("item") or {}
                it = item.get("type")
                if it == "UserMessage":
                    user_items += 1
                    content = item.get("content") or []
                    txt = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
                    n_img = sum(1 for c in content if isinstance(c, dict) and "image" in str(c.get("type")))
                    c = codex_user(txt + (" [image]" * n_img if n_img and not txt.strip() else ""))
                    if c:
                        s.events.append(Ev(t, c[0], c[1], c[2], {"typed": bool(item.get("client_id"))}))
                elif it == "AgentMessage":
                    content = item.get("content") or []
                    txt = "\n".join(c.get("text", "") for c in content if isinstance(c, dict)) if isinstance(content, list) else str(content)
                    if txt.strip():
                        s.events.append(Ev(t, "narr", txt, "", {"phase": item.get("phase")}))
                elif it == "ContextCompaction":
                    s.events.append(Ev(t, "compact", "", "boundary"))
                elif it == "McpToolCall" and item.get("tool") in ORCH:
                    # app tools such as codex_app.automation_update (heartbeats) surface only here
                    args = item.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    s.events.append(Ev(t, "orch", orch_summary(item["tool"], args if isinstance(args, dict) else {}), item["tool"]))
            elif et == "task_complete":
                if p.get("last_agent_message"):
                    s.events.append(Ev(t, "narr", p["last_agent_message"], "", {"final": True}))
            elif et == "turn_aborted":
                s.events.append(Ev(t, "interrupt", "", p.get("reason", "")))
            elif et == "thread_goal_updated":
                goal = p.get("goal") or {}
                s.events.append(Ev(t, "goal", goal.get("objective", ""), goal.get("status", "set")))
        elif typ == "response_item":
            it = p.get("type")
            if it in ("function_call", "custom_tool_call"):
                name = p.get("name") or it
                if name in ORCH:
                    raw = p.get("arguments") or p.get("input") or "{}"
                    try:
                        inp = json.loads(raw) if isinstance(raw, str) else raw
                    except json.JSONDecodeError:
                        inp = {}
                    inp = inp if isinstance(inp, dict) else {}
                    msg = str(inp.get("message", "")) if name == "spawn_agent" else ""
                    s.events.append(Ev(t, "orch", orch_summary(name, inp), name,
                                       {"prompt": "" if msg.startswith("gAAAAA") else msg}))
                else:
                    s.events.append(Ev(t, "tool", "", name))
            elif it == "message" and p.get("role") == "user":
                txt = "\n".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
                c = codex_user(txt)
                if c:
                    fallback.append(Ev(t, c[0], c[1], c[2], {"fallback": True}))
            elif it == "agent_message" and agent_path and p.get("recipient") == agent_path:
                txt = "\n".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
                s.events.append(Ev(t, "wake", txt, "task"))
    if not s.stamps:
        return None
    if not user_items and fallback:
        s.events = sorted(s.events + fallback, key=lambda e: e.ts)
    s.stamps.sort()
    return s


def fold_codex_children(sessions: list[Session]) -> list[Session]:
    """Codex subagent threads become intervals on their root thread; they are not sessions of their own."""
    by_thread = {s.thread: s for s in sessions if s.source == "codex" and s.thread}

    def root_of(x: Session) -> Session:
        cur, hops = x, 0
        while cur.parent_thread and cur.parent_thread in by_thread and hops < 8:
            cur, hops = by_thread[cur.parent_thread], hops + 1
        return cur

    roots = []
    for s in sessions:
        if s.source != "codex" or not s.parent_thread:
            roots.append(s)
            continue
        root = root_of(s)
        if root is not s and not root.parent_thread:
            root.subs.append(dict(kind="subagent", name=s.agent_name, start=s.start, end=s.end, teammate=False))
    return roots


# ------------------------------------------------------------ grok build ---
GROK_TRIVIAL = {"/compact", "/frok", "/model", "/resume-claude", "/resume-codex"}
USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.S)


def parse_grok(sdir: Path, machine: str) -> Session | None:
    """One Grok Build session directory (~/.grok/sessions/<enc cwd>/<sid>/)."""
    try:
        meta = json.loads((sdir / "summary.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    kind = meta.get("session_kind") or "interactive"
    if kind.startswith("subagent"):
        return None                         # children are folded in via the parent's subagent_spawned/finished
    sid = (meta.get("info") or {}).get("id") or sdir.name
    s = Session(source="grok-build", machine=machine, path=sdir, sid=sid,
                kind="programmatic" if kind == "headless" else "interactive",
                cwd=(meta.get("info") or {}).get("cwd", ""), branch=meta.get("head_branch") or "",
                title=meta.get("generated_title") or "")
    upd = sdir / "updates.jsonl"
    if not upd.exists():
        return None
    tools: dict[str, str] = {}              # toolCallId -> name
    last_msg: dict[str, Ev] = {}            # promptId -> last assistant message group
    open_subs: dict[str, dict] = {}
    pending_human: Ev | None = None
    for line in _lines(upd):
        rec = _load(line)
        if not isinstance(rec, dict):
            continue
        params = rec.get("params") or {}
        pm, u = params.get("_meta") or {}, params.get("update") or {}
        if not str(pm.get("eventId", "")).startswith(sid):
            continue                         # inherited from a forked/resumed parent
        t = ts_of(pm.get("agentTimestampMs"))
        if t is None:
            continue
        s.stamps.append(t)
        kind_u = u.get("sessionUpdate")
        um = u.get("_meta") or {}
        if kind_u == "user_message_chunk":
            content = u.get("content") or {}
            text = content.get("text") or ""
            if um.get("modelId"):
                s.models[um["modelId"]] += 1
            if um.get("hideFromScrollback"):
                s.events.append(Ev(t, "wake", text, "notify"))
                pending_human = None
                continue
            if um.get("interjection") or (um.get("promptIndex") is None and "<user_query>" in text):
                m = USER_QUERY_RE.search(text)
                s.events.append(Ev(t, "human", (m.group(1) if m else text).strip(), "", {"steer": True}))
                pending_human = None
                continue
            if text.lstrip().startswith("<system-reminder>"):
                s.events.append(Ev(t, "wake", text, "goal"))
                pending_human = None
                continue
            if content.get("type") == "image":
                if pending_human is not None and pending_human.meta.get("pi") == um.get("promptIndex"):
                    pending_human.text += " [image]"
                continue
            if pending_human is not None and pending_human.meta.get("pi") == um.get("promptIndex") and um.get("promptIndex") is not None:
                pending_human.text += "\n" + text   # multi-part prompt sharing one promptIndex
                continue
            if text.startswith("/") or um.get("hostTurn"):
                name, _, args = text.partition(" ")
                s.events.append(Ev(t, "cmd" if name in GROK_TRIVIAL else "command", args.strip(), name))
                pending_human = None
                continue
            pending_human = Ev(t, "human", text.strip(), "", {"pi": um.get("promptIndex")})
            s.events.append(pending_human)
        elif kind_u == "agent_message_chunk":
            pending_human = None
            key = f'{pm.get("promptId")}:{pm.get("streamStartMs")}'
            text = (u.get("content") or {}).get("text") or ""
            prev = last_msg.get(pm.get("promptId"))
            if prev is not None and prev.meta.get("mid") == key:
                prev.text += text
            else:
                ev = Ev(t, "narr", text, "", {"mid": key})
                s.events.append(ev)
                last_msg[pm.get("promptId")] = ev
        elif kind_u == "turn_completed":
            stop, ev = u.get("stop_reason"), last_msg.get(u.get("prompt_id"))
            if stop == "end_turn" and ev is not None:
                ev.meta["final"] = True
            elif stop in ("error", "rate_limit"):
                s.events.append(Ev(t, "apierr", str(u.get("agent_result") or stop)[:120]))
            elif stop == "cancelled":
                s.events.append(Ev(t, "interrupt", "", "cancelled"))
        elif kind_u == "tool_call":
            tm = um.get("x.ai/tool") or {}
            raw = u.get("rawInput") or {}
            name = tm.get("name") or (raw.get("variant") if isinstance(raw, dict) else None) or u.get("title") or "?"
            tools[u.get("toolCallId", "")] = name
            if name in ORCH:
                inp = raw if isinstance(raw, dict) else {}
                s.events.append(Ev(t, "orch", orch_summary(name, inp), name,
                                   {"prompt": inp.get("prompt", "") if name == "spawn_subagent" else ""}))
            else:
                s.events.append(Ev(t, "tool", "", name))
        elif kind_u == "tool_call_update":
            out = u.get("rawOutput") if isinstance(u.get("rawOutput"), dict) else {}
            ans = (out.get("UserAnswered") or {}).get("message") if isinstance(out.get("UserAnswered"), dict) else None
            if ans and tools.get(u.get("toolCallId", "")) == "ask_user_question":
                s.events.append(Ev(t, "answer", str(ans), "ask_user_question"))
        elif kind_u == "subagent_spawned":
            open_subs[u.get("subagent_id", "")] = dict(kind=u.get("subagent_type") or "subagent", name=u.get("description", ""),
                                                        start=t, end=t, teammate=False)
        elif kind_u == "subagent_finished":
            sub = open_subs.pop(u.get("subagent_id", ""), None)
            if sub:
                sub["end"] = t
                s.subs.append(sub)
        elif kind_u == "goal_updated":
            ev_name = u.get("last_event")
            if ev_name == "goal_created":
                s.events.append(Ev(t, "goal", u.get("objective", ""), "set"))
            elif ev_name == "goal_completed":
                s.events.append(Ev(t, "goal", u.get("objective", ""), "complete"))
        elif kind_u in ("auto_compact_completed",):
            s.events.append(Ev(t, "compact", "", "boundary", {"pre": u.get("tokens_before")}))
        elif kind_u == "retry_state" and u.get("type") in ("failed", "exhausted"):
            s.events.append(Ev(t, "apierr", str(u.get("error_type") or u.get("reason") or "retry exhausted")))
    if not s.stamps:
        return None
    s.stamps.sort()
    s.subs += [dict(x, end=s.end) for x in open_subs.values()]
    if not s.models and meta.get("current_model_id"):
        s.models[meta["current_model_id"]] += 1
    return s
