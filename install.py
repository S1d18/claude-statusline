#!/usr/bin/env python3
"""One-command installer for the Claude Code status line.

Copies statusline.py into ~/.claude/ and points settings.json at it.
Existing files are backed up (*.bak). Safe to re-run (idempotent).

Usage:
    python install.py
"""
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "statusline.py"
CLAUDE_DIR = Path.home() / ".claude"
DST = CLAUDE_DIR / "statusline.py"
SETTINGS = CLAUDE_DIR / "settings.json"


def backup(path: Path) -> None:
    if path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        print(f"  backed up {path.name} -> {bak.name}")


def main() -> int:
    if not SRC.exists():
        print(f"error: {SRC} not found", file=sys.stderr)
        return 1

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. copy the script
    backup(DST)
    shutil.copy2(SRC, DST)
    print(f"  installed {DST}")

    # 2. wire up settings.json (merge, don't clobber other keys)
    settings = {}
    if SETTINGS.exists():
        try:
            settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  warning: could not parse settings.json ({e}); starting fresh")
            settings = {}
        backup(SETTINGS)

    command = f'python "{DST}"'
    settings["statusLine"] = {"type": "command", "command": command, "padding": 0}
    SETTINGS.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  updated {SETTINGS} -> statusLine.command = {command}")

    print("\nDone. Open a new Claude Code session (or refresh) to see the status line.")
    print("Tip: edit the INPUT/OUTPUT cost constants at the top of statusline.py for your plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
