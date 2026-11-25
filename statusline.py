#!/usr/bin/env python3
"""Claude Code status line — Python port of the justindell gist + extras.

https://gist.github.com/justindell/bdb5c5ecf2549d116813f0817673b5fb (Ruby original)
Layout: 🤖 model | 🌿 [branch] | 📁 dir ✓/✗ | 🟢 <ctx-bar> | 💰 $cost | 🔋 5h N% · 7d M% | ⏳ reset | 🔁 [Ni/Mo]
  ✓ = git clean, ✗ = uncommitted changes;  ctx-bar = free space in context window;
  🔋 = share of the 5-hour session limit and the weekly limit still LEFT
       (claude.ai Pro/Max only — Claude Code sends `rate_limits` after the first reply);
  ⏳ reset = time left in the current 5-hour usage window before the limit resets.
Reads the status-line JSON from stdin. Windows/UTF-8 safe; never crashes.
"""
import sys, os, re, json, glob, subprocess
from decimal import Decimal
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Change these to match your Claude token costs https://www.anthropic.com/pricing#api
INPUT_COST_PER_MILLION = Decimal(3)
OUTPUT_COST_PER_MILLION = Decimal(15)

# Claude usage limits reset on a rolling 5-hour "session block" window.
SESSION_HOURS = 5

COLORS = {
    "reset":   "\x1b[0m",
    "gray":    "\x1b[90m",
    "red":     "\x1b[91m",
    "green":   "\x1b[92m",
    "yellow":  "\x1b[93m",
    "blue":    "\x1b[94m",
    "magenta": "\x1b[95m",
    "cyan":    "\x1b[96m",
    "white":   "\x1b[97m",
}


def color(name, text):
    return f"{COLORS[name]}{text}{COLORS['reset']}"


def rgb(r, g, b):
    return f"\x1b[38;2;{r};{g};{b}m"


def cwd(data):
    return (data.get("workspace") or {}).get("current_dir") or ""


_transcript_cache = {}


def transcript(data):
    path = data.get("transcript_path")
    if not path:
        return ""
    if path not in _transcript_cache:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                _transcript_cache[path] = f.read()
        except Exception:
            _transcript_cache[path] = ""
    return _transcript_cache[path]


def sum_token_field(text, field):
    regex = re.compile(r'"%s"\s*:\s*(\d+)' % re.escape(field))
    return sum(int(m) for m in regex.findall(text))


def input_tokens(data):
    return sum_token_field(transcript(data), "input_tokens")


def output_tokens(data):
    return sum_token_field(transcript(data), "output_tokens")


def thousands(number):
    return f"{int(number):,}"


# ── git state (branch + dirty), computed once ──
_git_cache = {}


def git_state(data):
    wd = cwd(data)
    if wd in _git_cache:
        return _git_cache[wd]
    branch, dirty = None, False
    if wd and os.path.isdir(wd):
        def g(*a):
            try:
                return subprocess.run(["git", "-C", wd, *a],
                                      capture_output=True, text=True, timeout=1.5).stdout.strip()
            except Exception:
                return ""
        branch = g("branch", "--show-current") or None
        if branch:
            dirty = bool(g("status", "--porcelain"))
    _git_cache[wd] = (branch, dirty)
    return _git_cache[wd]


# ── context window ──
def ctx_window(model_id):
    return 1_000_000 if "1m" in (model_id or "").lower() else 200_000


def context_pct(data):
    """Return used percentage of the context window, or None."""
    cw = data.get("context_window") or {}
    up = cw.get("used_percentage")
    if up is not None:
        try:
            return float(up)
        except Exception:
            pass
    # fallback: last assistant turn's total input tokens / window
    last = None
    for line in transcript(data).splitlines():
        if '"usage"' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        u = (o.get("message") or {}).get("usage")
        if u and o.get("type") == "assistant":
            last = u
    if last:
        used = (last.get("input_tokens", 0)
                + last.get("cache_read_input_tokens", 0)
                + last.get("cache_creation_input_tokens", 0))
        return used / ctx_window((data.get("model") or {}).get("id")) * 100.0
    if data.get("exceeds_200k_tokens"):
        return 100.0
    return None


def context_bar(pct, width=14):
    filled = round(pct * width / 100.0)
    out = []
    for i in range(width):
        pos = i * 100 // (width - 1)
        if pos <= 50:
            r, g, b = 220 * pos // 50, 200, 80 - 80 * pos // 50
        else:
            adj = pos - 50
            r, g, b = 220, 200 - 160 * adj // 50, 20 * adj // 50
        out.append((rgb(r, g, b) + "█") if i < filled else (rgb(60, 60, 60) + "░"))
    return "".join(out) + COLORS["reset"]


# ── session reset window (rolling 5h usage limit) ──
_TS_RE = re.compile(
    r'"timestamp"\s*:\s*"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)')


def _projects_root(data):
    """Locate the ~/.claude/projects dir; derive from transcript_path when
    possible so CLAUDE_CONFIG_DIR and custom homes are honored."""
    path = data.get("transcript_path")
    if path:
        # .../projects/<project-slug>/<session>.jsonl → up two levels
        root = os.path.dirname(os.path.dirname(path))
        if os.path.isdir(root):
            return root
    fallback = os.path.expanduser("~/.claude/projects")
    return fallback if os.path.isdir(fallback) else None


def _recent_timestamps(root, now):
    """All message timestamps (UTC) from transcripts touched within the last
    session window — the only files that can hold the active block."""
    cutoff = (now - timedelta(hours=SESSION_HOURS)).timestamp()
    out = []
    try:
        files = glob.glob(os.path.join(root, "*", "*.jsonl"))
    except Exception:
        return out
    for fp in files:
        try:
            if os.path.getmtime(fp) < cutoff:
                continue
            with open(fp, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue
        for y, mo, d, h, mi, s in _TS_RE.findall(text):
            try:
                ts = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s),
                              tzinfo=timezone.utc)
            except Exception:
                continue
            if ts >= now - timedelta(hours=SESSION_HOURS):
                out.append(ts)
    return out


def rate_limit(data, window):
    """`rate_limits.<window>` dict from Claude Code (five_hour / seven_day), or {}."""
    rl = data.get("rate_limits") or {}
    w = rl.get(window) if isinstance(rl, dict) else None
    return w if isinstance(w, dict) else {}


def session_reset_at(data, now=None):
    """When the current 5-hour usage window resets, or None if idle/unknown."""
    now = now or datetime.now(timezone.utc)
    # Prefer the authoritative value Claude Code reports for subscribers.
    try:
        ts = rate_limit(data, "five_hour").get("resets_at")
        if ts is not None:
            reset = datetime.fromtimestamp(float(ts), timezone.utc)
            return reset if reset > now else None
    except Exception:
        pass
    # Fallback: reconstruct the block from local transcript timestamps.
    root = _projects_root(data)
    if not root:
        return None
    stamps = _recent_timestamps(root, now)
    if not stamps:
        return None
    stamps.sort()
    window = timedelta(hours=SESSION_HOURS)
    block_start = stamps[0].replace(minute=0, second=0, microsecond=0)
    last = stamps[0]
    for ts in stamps[1:]:
        # A new block begins after a >5h idle gap or once the block is 5h old.
        if ts - block_start >= window or ts - last > window:
            block_start = ts.replace(minute=0, second=0, microsecond=0)
        last = ts
    reset = block_start + window
    return reset if reset > now else None


# ── sections ──
def section_model(data):
    name = (data.get("model") or {}).get("display_name") or "Unknown Model"
    return color("yellow", f"🤖 Claude {name}")


def section_git(data):
    branch, dirty = git_state(data)
    if not branch:
        return None
    return color("red" if dirty else "green", f"🌿 [{branch}]")


def section_workspace(data):
    wd = cwd(data)
    if not wd:
        return None
    display = os.path.basename(wd.rstrip("/\\"))
    seg = color("blue", f"📁 {display}")
    branch, dirty = git_state(data)
    if branch:
        seg += " " + (color("red", "✗") if dirty else color("green", "✓"))
    return seg


def section_context(data):
    pct = context_pct(data)
    if pct is None:
        return None
    pct = max(0.0, min(100.0, pct))
    free = 100.0 - pct
    emoji = "🚨" if pct >= 90 else "🔥" if pct >= 70 else "⚡" if pct >= 20 else "🟢"
    return f"{emoji} {context_bar(pct)} {color('gray', f'{free:.0f}% free')}"


# Fallback $/1M (input, output) by model-id prefix — used only when Claude Code
# doesn't send cost.total_cost_usd. Source: https://www.anthropic.com/pricing#api
MODEL_PRICES = {
    "claude-fable-5-2": (8, 40),
    "claude-fable-5": (10, 50),
    "claude-opus-5-5": (4, 20),
    "claude-opus-5": (5, 25),
    "claude-opus-4": (5, 25),
    "claude-sonnet-5": (2, 10),
    "claude-sonnet-4": (3, 15),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4": (1, 5),
}


def model_prices(data):
    mid = ((data.get("model") or {}).get("id") or "").lower()
    for prefix in sorted(MODEL_PRICES, key=len, reverse=True):
        if mid.startswith(prefix):
            i, o = MODEL_PRICES[prefix]
            return Decimal(str(i)), Decimal(str(o))
    return INPUT_COST_PER_MILLION, OUTPUT_COST_PER_MILLION


def section_cost(data):
    # Preferred: Claude Code's own figure (right per-model prices incl. cache).
    try:
        total = (data.get("cost") or {}).get("total_cost_usd")
        if total is not None:
            total = float(total)
            return color("green", f"💰 ${total:.2f}") if total > 0 else None
    except Exception:
        pass
    pin, pout = model_prices(data)
    ic = Decimal(input_tokens(data)) * pin / Decimal(1_000_000)
    oc = Decimal(output_tokens(data)) * pout / Decimal(1_000_000)
    total = round(float(ic + oc), 4)
    if total == 0.0:
        return None
    return color("green", f"💰 ${total}")


def _left_pct(data, window):
    used = rate_limit(data, window).get("used_percentage")
    if used is None:
        return None
    try:
        return max(0.0, min(100.0, 100.0 - float(used)))
    except Exception:
        return None


def section_limits(data):
    parts = []
    for label, window in (("5h", "five_hour"), ("7d", "seven_day")):
        left = _left_pct(data, window)
        if left is None:
            continue
        hue = "red" if left < 10 else "yellow" if left < 30 else "green"
        parts.append(color(hue, f"{label} {left:.0f}%"))
    if not parts:
        return None
    return "🔋 " + color("gray", " · ").join(parts)


def section_reset(data):
    reset = session_reset_at(data)
    if reset is None:
        return None
    left = reset - datetime.now(timezone.utc)
    mins = int(left.total_seconds() // 60)
    if mins < 0:
        return None
    h, m = divmod(mins, 60)
    label = f"{h}h{m:02d}m" if h else f"{m}m"
    hue = "red" if mins < 30 else "yellow" if mins < 120 else "green"
    return color(hue, f"⏳ {label}")


def section_transfer(data):
    i = color("cyan", f"{thousands(input_tokens(data))}i")
    o = color("magenta", f"{thousands(output_tokens(data))}o")
    return f"🔁 [{i}/{o}]"


def main():
    try:
        data = json.loads(sys.stdin.read().strip())
    except Exception:
        data = {}

    sections = [
        section_model(data),
        section_git(data),
        section_workspace(data),
        section_context(data),
        section_cost(data),
        section_limits(data),
        section_reset(data),
        section_transfer(data),
    ]
    sys.stdout.write(" | ".join(s for s in sections if s))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout.write(f"Claude | statusline error: {e}")
