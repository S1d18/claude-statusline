#!/usr/bin/env python3
"""Claude Code status line — Python port of the justindell gist + extras.

https://gist.github.com/justindell/bdb5c5ecf2549d116813f0817673b5fb (Ruby original)
Layout: 🤖 model | 🌿 [branch] | 📁 dir ✓/✗ | 🟢 <ctx-bar> | 💰 $cost | 🔁 [Ni/Mo]
  ✓ = git clean, ✗ = uncommitted changes;  ctx-bar = free space in context window.
Reads the status-line JSON from stdin. Windows/UTF-8 safe; never crashes.
"""
import sys, os, re, json, subprocess
from decimal import Decimal

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Change these to match your Claude token costs https://www.anthropic.com/pricing#api
INPUT_COST_PER_MILLION = Decimal(3)
OUTPUT_COST_PER_MILLION = Decimal(15)

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


def section_cost(data):
    ic = Decimal(input_tokens(data)) * INPUT_COST_PER_MILLION / Decimal(1_000_000)
    oc = Decimal(output_tokens(data)) * OUTPUT_COST_PER_MILLION / Decimal(1_000_000)
    total = round(float(ic + oc), 4)
    if total == 0.0:
        return None
    return color("green", f"💰 ${total}")


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
        section_transfer(data),
    ]
    sys.stdout.write(" | ".join(s for s in sections if s))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout.write(f"Claude | statusline error: {e}")
