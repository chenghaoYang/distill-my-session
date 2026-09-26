"""Deterministic declassification layer (stdlib only).

Order matters: secrets first, then URLs and emails, then paths and names, then generic identifiers.
The same Redactor instance keeps aliases stable across a whole run.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

def rx(pattern: str, flags: int = 0) -> re.Pattern:
    """ASCII word semantics: CJK text around an identifier must still count as a boundary."""
    return re.compile(pattern, flags | re.A)


CONFIG_DIR = Path(os.environ.get("DISTILL_CONFIG_DIR", Path.home() / ".config" / "distill-my-session"))

# Hosts whose name alone is not an identifier. Paths are always dropped.
PUBLIC_HOSTS = {
    "github.com", "gist.github.com", "raw.githubusercontent.com", "gitlab.com", "arxiv.org",
    "huggingface.co", "pypi.org", "npmjs.com", "www.npmjs.com", "docs.python.org", "stackoverflow.com",
    "en.wikipedia.org", "zh.wikipedia.org", "docs.anthropic.com", "docs.claude.com", "code.claude.com",
    "platform.openai.com", "openai.com", "anthropic.com", "www.anthropic.com", "claude.ai", "chatgpt.com",
    "www.perplexity.ai", "perplexity.ai", "x.com", "twitter.com", "youtube.com", "www.youtube.com",
    "localhost", "127.0.0.1",
}

# Directory names too generic to count as project identifiers.
GENERIC_DIRS = {
    "developer", "dev", "code", "src", "work", "workspace", "projects", "project", "repos", "repo", "git",
    "home", "tmp", "temp", "desktop", "documents", "downloads", "build", "dist", "scripts", "test", "tests",
    "app", "apps", "lib", "docs", "data", "notebooks", "playground", "sandbox", "demo", "main", "master",
}

SECRET_PATTERNS = [
    ("pem", rx(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("token", rx(r"\b(?:sk-ant-[A-Za-z0-9_\-]{16,}|sk-(?:proj-)?[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"
                         r"|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_\-]{20,}|xox[abprs]-[A-Za-z0-9\-]{10,}"
                         r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|hf_[A-Za-z0-9]{30,}|pplx-[A-Za-z0-9]{30,}"
                         r"|r8_[A-Za-z0-9]{30,}|nvapi-[A-Za-z0-9_\-]{30,})")),
    ("jwt", rx(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("bearer", rx(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/\-]{20,}=*")),
    ("assignment", rx(r"(?i)\b([A-Z0-9_\-]*(?:api[_\-]?key|secret|token|passwd|password|pwd|cookie|session[_\-]?id|access[_\-]?key|private[_\-]?key)[A-Z0-9_\-]*)"
                              r"(\s*[:=]\s*[\"']?)([^\s\"',;]{6,})")),
]
URL_RE = rx(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s<>\"'`)\]]+")
EMAIL_RE = rx(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?![A-Za-z])")
TILDE_RE = rx(r"~/(?!\.claude\b|\.codex\b|\.agents\b|\.config\b|\[)[^\s\"'`)\]\[<>]+")
IPV4_RE = rx(r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])")
PHONE_RE = rx(r"(?<!\d)(?:\+?86[\s\-]?)?1[3-9]\d{9}(?!\d)|\+\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}\b")
UUID_RE = rx(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
LONGHEX_RE = rx(r"\b[0-9a-fA-F]{32,}\b")
BLOB_RE = rx(r"[A-Za-z0-9+/_\-]{40,}={0,2}")
HOME_RE = rx(r"(?:/Users|/home)/([A-Za-z0-9._\-]+)")
SYS_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/etc/", "/opt/homebrew/", "/System/", "/Library/", "/Applications/",
                "/dev/", "/tmp/", "/private/tmp/", "/proc/", "/var/log/")
ABS_PATH_RE = rx(r"(?<![\w.~/])/(?:[\w.\-@+]+/){1,}[\w.\-@+]*")
SSH_RE = rx(r"(?<![\w-])(ssh|scp|rsync|sftp|mosh)[ \t]+([^\n`;|&]*)")
SSH_VALUE_FLAGS = set("bcDEeFIiJLlmOopQRSWw")


def _ssh_args(args: str) -> str:
    """Mask the first non-flag operand (the host, maybe user@host:path) of an ssh-family command."""
    toks = re.split(r"(\s+|[，。；、])", args)
    i, skip_next = 0, False
    while i < len(toks):
        tok = toks[i]
        if not tok or tok.isspace():
            i += 1
            continue
        if skip_next:
            skip_next = False
        elif tok.startswith("-"):
            skip_next = len(tok) == 2 and tok[1] in SSH_VALUE_FLAGS
        elif tok.startswith(("'", '"', "[", "~", "./", "/")):
            pass
        else:
            host, sep, rest = tok.partition(":")
            toks[i] = "[HOST]" + (sep + rest if sep else "")
            break
        i += 1
    return "".join(toks)
USERHOST_RE = rx(r"\b[\w.\-]+@[\w\-]+(?:\.[\w\-]+)*(?=:)")
MD_ESCAPE_RE = rx(r"\\([_@*\[\]()#.!\-`>~|{}+&])")
DOMAIN_RE = rx(r"(?<![\w.@/-])(?:[a-z0-9-]+\.)+(?:com|cn|net|org|io|ai|co|edu|gov|hk|tw|jp|kr|sg|us|uk|de|fr)(?![\w.-])", re.I)
HOSTNAME_RE = rx(r"\b[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.(?:internal|corp|intra|lan|local|private|cluster\.local)\b")


def shannon(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in freq.values())


def identity_variants() -> list[re.Pattern]:
    """$USER, home dir name, git user.name / email handle, and swapped-order pinyin variants (weizhang -> zhangwei)."""
    import subprocess
    names = {os.environ.get("USER", ""), Path.home().name}
    for key in ("user.name", "user.email"):
        try:
            v = subprocess.run(["git", "config", "--global", key], capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            v = ""
        v = v.split("@")[0].split("+")[-1]
        names |= {v.replace(" ", "")} | set(v.split())
    names = {n.lower() for n in names if n}
    for base in list(names):
        for tok in list(names):
            if tok != base and len(tok) >= 3 and base.startswith(tok) and len(base) - len(tok) >= 2:
                rest = base[len(tok):]
                names |= {rest + tok, f"{tok}.{rest}", f"{rest}.{tok}", f"{tok}_{rest}", f"{rest}_{tok}", f"{tok}-{rest}", f"{rest}-{tok}"}
    return [rx(r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])", re.I) for n in sorted(names, key=len, reverse=True) if len(n) >= 5]


def load_list(path: Path) -> list[tuple[re.Pattern, str]]:
    """Denylist / allowlist lines: `term`, `term => alias`, `re:<regex> => alias`; '#' comments."""
    out: list[tuple[re.Pattern, str]] = []
    if not path or not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        alias = "[REDACTED]"
        if "=>" in line:
            line, alias = (x.strip() for x in line.split("=>", 1))
        if line.startswith("re:"):
            pat = rx(line[3:], re.I)
        else:
            pat = rx(r"(?<![A-Za-z0-9])" + re.escape(line) + r"(?![A-Za-z0-9])", re.I)
        out.append((pat, alias))
    return out


def load_denylists(explicit: Path | None, aliases: Path | None) -> list[tuple[re.Pattern, str]]:
    """Global list (~/.config/distill-my-session/denylist.txt, or --denylist) plus the run's private/denylist.txt."""
    out = load_list(explicit or CONFIG_DIR / "denylist.txt")
    if aliases:
        out += load_list(aliases.parent / "denylist.txt")
    return out


class Redactor:
    def __init__(self, denylist: Path | None = None, allowlist: Path | None = None, aliases: Path | None = None,
                 keep_urls: bool = False):
        self.deny = load_denylists(denylist, aliases)
        self.allow_terms = [p for p, _ in load_list(allowlist or CONFIG_DIR / "allowlist.txt")]
        self.keep_urls = keep_urls
        self.aliases_path = aliases
        self.aliases: dict[str, dict[str, str]] = {"project": {}, "session": {}, "machine": {}}
        if aliases and aliases.exists():
            self.aliases.update(json.loads(aliases.read_text()))
        self.user = os.environ.get("USER", "")
        self.names = identity_variants()
        self.hits: dict[str, int] = {}
        self._project_res: list[tuple[re.Pattern, str]] = []
        self._rebuild_projects()

    # ---- aliases -------------------------------------------------------
    def alias(self, kind: str, real: str, prefix: str) -> str:
        table = self.aliases.setdefault(kind, {})
        if real not in table:
            table[real] = f"{prefix}{len(table) + 1:02d}"
            if kind == "project":
                self._rebuild_projects()
        return table[real]

    def _rebuild_projects(self) -> None:
        res = []
        for real, al in sorted(self.aliases.get("project", {}).items(), key=lambda kv: -len(kv[0])):
            name = Path(real).name
            if len(name) >= 4 and name.lower() not in GENERIC_DIRS:
                res.append((rx(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.I), al))
        self._project_res = res

    def save(self) -> None:
        if self.aliases_path:
            self.aliases_path.parent.mkdir(parents=True, exist_ok=True)
            self.aliases_path.write_text(json.dumps(self.aliases, indent=1, ensure_ascii=False))

    def _deny_alias(self, hit: str, alias: str) -> str:
        """Distinct strings behind one alias get numbered ([MODEL-X·2]) so the reader can still tell them apart."""
        self._count("denylist")
        if not (alias.startswith("[") and alias.endswith("]")):
            return alias
        table = self.aliases.setdefault("deny", {}).setdefault(alias, {})
        key = hit.lower()
        if key not in table:
            table[key] = len(table) + 1
        return f"{alias[:-1]}·{table[key]}]"

    # ---- core ----------------------------------------------------------
    def _count(self, cls: str) -> None:
        self.hits[cls] = self.hits.get(cls, 0) + 1

    def _url(self, m: re.Match) -> str:
        url = m.group(0)
        if any(p.search(url) for p in self.allow_terms):
            return url
        host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://(?:[^@/]*@)?", "", url).split("/")[0].split(":")[0].lower()
        self._count("url")
        if self.keep_urls or host in PUBLIC_HOSTS:
            return f"[URL:{host}]"
        return "[URL]"

    def __call__(self, text: str) -> str:
        if not text:
            return text
        protected: list[str] = []

        def protect(m: re.Match) -> str:
            protected.append(m.group(0))
            return f"\x00{len(protected) - 1}\x00"

        text = MD_ESCAPE_RE.sub(r"\1", text)      # desktop apps store markdown-escaped text: user\_x, a\@b.com
        for pat in self.allow_terms:
            text = pat.sub(protect, text)
        for cls, pat in SECRET_PATTERNS:
            if cls == "assignment":
                text = pat.sub(lambda m: (self._count("secret"), f"{m.group(1)}{m.group(2)}[SECRET]")[1], text)
            else:
                text = pat.sub(lambda m: (self._count("secret"), "[SECRET]")[1], text)
        text = URL_RE.sub(self._url, text)
        text = EMAIL_RE.sub(lambda m: (self._count("email"), "[EMAIL]")[1], text)
        for pat, al in self.deny:
            text = pat.sub(lambda m, al=al: self._deny_alias(m.group(0), al), text)
        text = HOME_RE.sub("~", text)
        text = ABS_PATH_RE.sub(lambda m: m.group(0) if m.group(0).startswith(SYS_PREFIXES) else (self._count("path"), "[PATH]")[1], text)
        text = TILDE_RE.sub(lambda m: (self._count("path"), "~/[PATH]")[1], text)
        text = SSH_RE.sub(lambda m: (self._count("host"), f"{m.group(1)} {_ssh_args(m.group(2))}")[1], text)
        text = USERHOST_RE.sub(lambda m: (self._count("host"), "[USER@HOST]")[1], text)
        for pat, al in self._project_res:
            text = pat.sub(lambda m, al=al: (self._count("project"), al)[1], text)
        for pat in self.names:
            text = pat.sub(lambda m: (self._count("identity"), "[USER]")[1], text)
        text = HOSTNAME_RE.sub(lambda m: (self._count("host"), "[HOST]")[1], text)
        text = DOMAIN_RE.sub(lambda m: m.group(0) if m.group(0).lower() in PUBLIC_HOSTS or m.group(0).lower().removeprefix("www.") in PUBLIC_HOSTS
                             else (self._count("domain"), "[DOMAIN]")[1], text)
        text = IPV4_RE.sub(lambda m: m.group(0) if m.group(0).startswith("127.") else (self._count("ip"), "[IP]")[1], text)
        text = PHONE_RE.sub(lambda m: (self._count("phone"), "[PHONE]")[1], text)
        text = UUID_RE.sub("[UUID]", text)
        text = LONGHEX_RE.sub("[HEX]", text)
        text = BLOB_RE.sub(lambda m: (self._count("blob"), "[BLOB]")[1] if shannon(m.group(0)) > 4.2 else m.group(0), text)
        for i, orig in enumerate(protected):
            text = text.replace(f"\x00{i}\x00", orig)
        return text


# ---- leak check ------------------------------------------------------------
LEAK_PATTERNS = [(cls, pat) for cls, pat in SECRET_PATTERNS if cls != "assignment"] + [
    ("email", EMAIL_RE), ("ip", IPV4_RE), ("phone", PHONE_RE), ("abs-path", HOME_RE), ("host", HOSTNAME_RE),
    ("uuid", UUID_RE), ("abs-path", ABS_PATH_RE), ("domain", DOMAIN_RE), ("ssh-target", SSH_RE), ("url-path", rx(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s\])>]+/[^\s\])>]+")),
]


def leakcheck(root: Path, denylist: Path | None, aliases: Path | None, allowlist: Path | None = None) -> list[tuple[str, int, str, str]]:
    deny = load_denylists(denylist, aliases)
    allow = [p for p, _ in load_list(allowlist or CONFIG_DIR / "allowlist.txt")]
    real_names: list[re.Pattern] = []
    real_names.extend(identity_variants())
    if aliases and aliases.exists():
        for kind, table in json.loads(aliases.read_text()).items():
            if kind == "deny":
                for hits in table.values():
                    real_names.extend(rx(r"(?<![A-Za-z0-9])" + re.escape(h) + r"(?![A-Za-z0-9])", re.I) for h in hits if len(h) >= 3)
                continue
            for real in table:
                name = Path(real).name if kind == "project" else real
                if kind == "project" and (len(name) < 4 or name.lower() in GENERIC_DIRS):
                    continue
                if kind == "machine" and name.lower() in ("local", "localhost") or len(name) < 4:
                    continue
                if kind == "session":
                    name = real.split(":")[-1]
                real_names.append(rx(r"(?<![\w])" + re.escape(name) + r"(?![\w])", re.I))
    findings = []
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    for f in files:
        if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ico"}:
            continue
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            scrub = line
            for p in allow:
                scrub = p.sub(" ", scrub)
            checks = [(c, p) for c, p in LEAK_PATTERNS] + [("denylist", p) for p, _ in deny] + [("real-name", p) for p in real_names]
            for cls, pat in checks:
                for m in pat.finditer(scrub):
                    hit = m.group(0)
                    if cls == "ip" and hit.startswith("127."):
                        continue
                    if cls == "url-path" and any(h in hit for h in ("github.com/justinatusa/vocabulary-first",)):
                        continue
                    masked = hit[:3] + "…" + hit[-2:] if len(hit) > 6 else "…"
                    findings.append((str(f.relative_to(root) if root.is_dir() else f.name), n, cls, masked))
            for m in BLOB_RE.finditer(scrub):
                if shannon(m.group(0)) > 4.2:
                    findings.append((str(f.relative_to(root) if root.is_dir() else f.name), n, "high-entropy", m.group(0)[:3] + "…"))
    return findings
