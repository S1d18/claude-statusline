# Claude Code Status Line

A compact, colorful status line for [Claude Code](https://claude.com/claude-code) — model, git branch + dirty state, working directory, a live context-window gauge, session cost, how much of the 5-hour and weekly limits is left, time left until the usage limit resets, and token transfer.

![status line screenshot](assets/statusline.png)

```
🤖 Claude Opus 4.8 | 🌿 [main] | 📁 my-project ✓ | 🟢 ████░░░░░░ 60% free | 💰 $0.91 | 🔋 5h 76% · 7d 58% | ⏳ 2h37m | 🔁 [134i/60,734o]
```

## What it shows

| Segment | Meaning |
|---|---|
| 🤖 **Claude \<model\>** | Current model display name |
| 🌿 **[branch]** | Git branch — green when clean, red when dirty (hidden outside a repo) |
| 📁 **dir ✓ / ✗** | Working directory basename; `✓` git clean, `✗` uncommitted changes |
| 🟢 **bar + % free** | Context-window gauge — how much room is left before auto-compact. Fill goes green→yellow→red; icon escalates 🟢→⚡→🔥→🚨. Understands the 1M-token window. |
| 💰 **$cost** | Session cost, computed from transcript tokens |
| 🔋 **5h · 7d** | Percent **left** of the 5-hour session limit and the weekly limit, straight from Claude Code's `rate_limits`. Green ≥30%, yellow <30%, red <10%. Only for claude.ai Pro/Max, appears after the first reply. |
| ⏳ **reset** | Time left in the current rolling 5-hour usage window before the limit resets. Green >2h, yellow <2h, red <30m. Hidden when idle. |
| 🔁 **[Ni/Mo]** | Total input (`i`, cyan) / output (`o`, magenta) tokens this session |

Pure Python, no dependencies, no `jq`. Works on Windows / macOS / Linux and never crashes the footer — on any error it still prints a minimal line.

## Install

Requires Python 3.8+ on your `PATH`.

```bash
git clone https://github.com/S1d18/claude-statusline.git
cd claude-statusline
python install.py
```

The installer copies `statusline.py` to `~/.claude/statusline.py` and sets `statusLine` in `~/.claude/settings.json` (backing up anything it replaces to `*.bak`). Open a new Claude Code session to see it.

### Manual install

Copy `statusline.py` anywhere, then add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python \"C:\\Users\\you\\.claude\\statusline.py\"",
    "padding": 0
  }
}
```

## Configure cost

Edit the constants at the top of `statusline.py` to match your [pricing](https://www.anthropic.com/pricing#api):

```python
INPUT_COST_PER_MILLION  = Decimal(3)
OUTPUT_COST_PER_MILLION = Decimal(15)
```

> Note: cost & 🔁 tokens sum every `input_tokens`/`output_tokens` in the transcript, which includes cache reads/writes — so the figure runs higher than the raw billed input. It's a session-activity gauge, not an invoice.

> Note: when Claude Code reports `rate_limits.five_hour.resets_at` (Pro/Max), ⏳ uses it as-is. Otherwise the reset window is **global** across all your projects, not per-session. It's inferred from transcript timestamps under `~/.claude/projects` — the block starts on your first activity (floored to the hour) and resets 5 hours later. Only files touched within the last 5 hours are read, so it stays fast.

## Credits

Ported to Python and extended (git icon, context gauge) from a Ruby
[gist by @justindell](https://gist.github.com/justindell/bdb5c5ecf2549d116813f0817673b5fb).

## License

MIT — see [LICENSE](LICENSE).
