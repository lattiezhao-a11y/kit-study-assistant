#!/usr/bin/env python3
"""Small systemd replacement for Docker; Raspberry Pi deployments keep systemd timers.

It keeps bot.py running, runs scheduled scripts in German time, catches up missed
email checks after container downtime, and skips a job whose previous invocation is
still running. Use --no-bot, --list, or --run NAME for the respective modes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from common import DATA, TZ, save_json

HERE = Path(__file__).resolve().parent
STATE_FILE = DATA / "scheduler_state.json"   # Last scheduled slot executed for each job.
TICK = 20                 # Seconds between time checks.
ON_TIME = 120             # Execution window for non-catch-up jobs; old reminders are not sent after restart.
BOT_RESTART_DELAY = 30    # Seconds to wait before restarting a stopped bot.

# name: hour(s), minute, scripts to run in order, and whether missed runs catch up.
JOBS: dict[str, dict] = {
    "mail":    {"hours": [1, 7, 13, 19], "minute": 30, "catch_up": True,
                "cmds": [["digest.py"], ["ilias_sync.py"]]},           # Email and ILIAS.
    "morning": {"hours": [7], "minute": 0, "catch_up": False,
                "cmds": [["remind.py", "--morning"]]},                 # Morning summary.
    "remind":  {"hours": list(range(7, 24)), "minute": 5, "catch_up": False,
                "cmds": [["remind.py"]]},                              # Reminders for deadlines within three hours.
}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- Time calculations (pure functions called directly by tests)

def latest_slot(job: dict, now: dt.datetime) -> dt.datetime:
    """Return the most recent scheduled slot at or before now."""
    for back in (0, 1):
        day = (now - dt.timedelta(days=back)).date()
        for h in sorted(job["hours"], reverse=True):
            t = dt.datetime.combine(day, dt.time(h, job["minute"]), tzinfo=now.tzinfo)
            if t <= now:
                return t
    raise ValueError("The timetable is empty")


def next_slot(job: dict, now: dt.datetime) -> dt.datetime:
    """Return the nearest scheduled slot after now."""
    for ahead in (0, 1):
        day = (now + dt.timedelta(days=ahead)).date()
        for h in sorted(job["hours"]):
            t = dt.datetime.combine(day, dt.time(h, job["minute"]), tzinfo=now.tzinfo)
            if t > now:
                return t
    raise ValueError("The timetable is empty")


def due(job: dict, now: dt.datetime, last: dt.datetime | None) -> dt.datetime | None:
    """Return the scheduled slot to run now, or None when no run is due.

    last is the slot associated with the previous run. None means no prior run; the
    first startup records the current slot without running, like systemd.
    """
    slot = latest_slot(job, now)
    if last is not None and slot <= last:
        return None                                   # This scheduled slot has already run.
    if job["catch_up"]:
        return slot if last is not None else None
    return slot if (now - slot).total_seconds() < ON_TIME else None


# ---------------------------------------------------------------- Execution

def load_state() -> dict[str, dt.datetime]:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {k: dt.datetime.fromisoformat(v) for k, v in raw.items()}
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, dt.datetime]) -> None:
    save_json(STATE_FILE, {k: v.isoformat() for k, v in state.items()})


class Runner:
    def __init__(self, with_bot: bool) -> None:
        self.with_bot = with_bot
        self.stopping = threading.Event()
        self.bot: subprocess.Popen | None = None
        self.bot_down_since: float | None = None
        self.jobs: dict[str, threading.Thread] = {}
        self.procs: set[subprocess.Popen] = set()
        self.lock = threading.Lock()

    def run_job(self, name: str) -> None:
        """Run all scripts for a job in order; continue after failures like systemd's leading “-”."""
        for cmd in JOBS[name]["cmds"]:
            if self.stopping.is_set():
                return
            log(f"{name}: start {' '.join(cmd)}")
            p = subprocess.Popen([sys.executable, "-u", *cmd], cwd=HERE)
            with self.lock:
                self.procs.add(p)
            code = p.wait()
            with self.lock:
                self.procs.discard(p)
            log(f"{name}: {cmd[0]} finished (exit code {code})")

    def start_job(self, name: str) -> bool:
        t = self.jobs.get(name)
        if t and t.is_alive():
            log(f"{name}: previous run still going, skipping this one")
            return False
        t = threading.Thread(target=self.run_job, args=(name,), daemon=True)
        self.jobs[name] = t
        t.start()
        return True

    def check_bot(self) -> None:
        if not self.with_bot or self.stopping.is_set():
            return
        if self.bot and self.bot.poll() is None:
            return                                    # Already running.
        if self.bot:                                  # The bot has just been found stopped.
            log(f"bot: exited (exit code {self.bot.returncode}), restarting in {BOT_RESTART_DELAY} s")
            self.bot, self.bot_down_since = None, time.monotonic()
        if self.bot_down_since and time.monotonic() - self.bot_down_since < BOT_RESTART_DELAY:
            return
        log("bot: starting")
        self.bot = subprocess.Popen([sys.executable, "-u", "bot.py"], cwd=HERE)
        self.bot_down_since = None

    def stop(self, *_args) -> None:
        if self.stopping.is_set():
            return
        log("Stop signal received, shutting down")
        self.stopping.set()
        with self.lock:
            procs = list(self.procs)
        for p in procs + ([self.bot] if self.bot else []):
            if p.poll() is None:
                p.terminate()

    def loop(self) -> None:
        state = load_state()
        now = dt.datetime.now(TZ)
        for name, job in JOBS.items():               # First startup: record slots without running jobs.
            if name not in state:
                state[name] = latest_slot(job, now)
        save_state(state)
        log(f"Scheduler started (data folder {DATA}), bot: {'on' if self.with_bot else 'off'}")
        while not self.stopping.is_set():
            self.check_bot()
            now = dt.datetime.now(TZ)
            for name, job in JOBS.items():
                slot = due(job, now, state.get(name))
                if slot and self.start_job(name):
                    state[name] = slot
                    save_state(state)
            self.stopping.wait(TICK)
        for p in [self.bot] if self.bot else []:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        log("Stopped")


def main() -> int:
    ap = argparse.ArgumentParser(description="Small scheduler that replaces systemd (for Docker)")
    ap.add_argument("--no-bot", action="store_true", help="no chat bot, scheduled jobs only")
    ap.add_argument("--list", action="store_true", help="print the timetable and exit")
    ap.add_argument("--run", choices=sorted(JOBS), help="run one job once, right now")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.list:
        now = dt.datetime.now(TZ)
        for name, job in JOBS.items():
            cmds = " → ".join(" ".join(c) for c in job["cmds"])
            print(f"{name:8} minute {job['minute']:02d}, hours {job['hours']}  next "
                  f"{next_slot(job, now):%m-%d %H:%M}  {cmds}")
        return 0

    runner = Runner(with_bot=not args.no_bot)
    signal.signal(signal.SIGTERM, runner.stop)
    signal.signal(signal.SIGINT, runner.stop)
    if args.run:
        runner.run_job(args.run)
        return 0
    runner.loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
