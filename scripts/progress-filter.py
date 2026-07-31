#!/usr/bin/env python3
"""Redraw Docker/Ollama pull progress as a single updating line.

Docker's and Ollama's own progress output only redraws in place when attached
to an interactive TTY. Piped through a log, a non-interactive shell, or the
VSCode extension's spawned process, each update prints as its own new line
instead. This reads structured progress events (Docker's `--progress=json`
events and Ollama's NDJSON pull stream both carry current/completed + total
byte counts) from stdin and redraws a single line, appending the final byte
count to the totals file (argv[2]) so the caller can report a grand total
downloaded at the end of the run.

Usage: progress-filter.py <label> [totals-file]
"""
import json
import sys
import time


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "Working"
    totals_file = sys.argv[2] if len(sys.argv) > 2 else ""
    seen = {}
    last_draw = 0.0

    def draw(force=False):
        nonlocal last_draw
        now = time.time()
        if not force and now - last_draw < 0.2:
            return
        last_draw = now
        downloaded = sum(v["current"] for v in seen.values())
        total = sum(v["total"] for v in seen.values() if v["total"])
        if total:
            line = f"  {label}: {human(downloaded)} / {human(total)} downloaded"
        elif downloaded:
            line = f"  {label}: {human(downloaded)} downloaded"
        else:
            line = f"  {label}…"
        sys.stdout.write("\r\033[K" + line)
        sys.stdout.flush()

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue  # plain-text chatter, not a structured progress event
        if not isinstance(obj, dict):
            continue
        # A layer's id is reused across phases (Downloading, then Extracting,
        # etc.) with unrelated meanings for "current" (bytes vs. files
        # extracted). Only byte-count the download phase, or Ollama's pull
        # stream, which has no competing "text" field of its own.
        text = obj.get("text")
        if text is not None and text != "Downloading":
            continue
        detail = obj.get("progressDetail") or {}
        current = obj.get("current", detail.get("current", obj.get("completed")))
        total = obj.get("total", detail.get("total"))
        if current is None:
            continue
        ident = obj.get("id") or obj.get("digest") or obj.get("status") or "default"
        prev = seen.get(ident, {"current": 0, "total": 0})
        seen[ident] = {"current": current, "total": total or prev["total"]}
        draw()

    draw(force=True)
    sys.stdout.write("\n")
    sys.stdout.flush()
    if totals_file:
        downloaded_total = sum(v["current"] for v in seen.values())
        try:
            with open(totals_file, "a") as fh:
                fh.write(f"{downloaded_total}\n")
        except OSError:
            pass


if __name__ == "__main__":
    main()
