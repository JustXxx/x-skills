#!/usr/bin/env python3
"""
x-poster execution wrapper.

Finds the xpost binary and executes the specified command.
Designed to be called by AI agents.

Usage:
    python3 scripts/xpost_run.py <command> [args...]

Examples:
    python3 scripts/xpost_run.py check
    python3 scripts/xpost_run.py post 'Hello world!'
    python3 scripts/xpost_run.py read 'https://x.com/user/status/123' --json
    python3 scripts/xpost_run.py timeline '@NASA' -n 5 --json
    python3 scripts/xpost_run.py search 'AI news' -n 10 --latest --json
"""

import shutil
import subprocess
import sys


def find_xpost_binary() -> str:
    """Find the xpost binary in PATH."""
    xpost = shutil.which("xpost")
    if xpost:
        return xpost
    raise FileNotFoundError(
        "xpost command not found in PATH.\n"
        "Run 'pip install -e <project_root>' first to install x-poster."
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 xpost_run.py <command> [args...]")
        print("Commands: post, video, quote, article, read, timeline, search, check")
        sys.exit(1)

    try:
        xpost = find_xpost_binary()
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    cmd = [xpost] + sys.argv[1:]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
