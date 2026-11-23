#!/usr/bin/env python3
"""
代替 systemd 的小调度器：Docker 里用它（树莓派上继续用 deploy/ 里的 systemd 定时器）

  - bot.py 一直运行；意外退出了，等 30 秒自动重启
  - 按 JOBS 的时间表运行定时脚本（德国时间），和 deploy/*.timer 完全一样
  - 容器关着的时候错过了邮件检查，启动后马上补一次（像 systemd 的 Persistent=true）
  - 同一个任务上一次还没跑完，就跳过这一次

用法：
  python3 scheduler.py              正常运行（Docker 的启动命令）
  python3 scheduler.py --no-bot     只跑定时任务，不开聊天机器人
  python3 scheduler.py --list       打印时间表和接下来的运行时间，然后退出
  python3 scheduler.py --run 名字   马上运行某个任务一次（测试用，例如 --run morning）
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
from zoneinfo import ZoneInfo

from digest import DATA

HERE = Path(__file__).resolve().parent
TZ = ZoneInfo("Europe/Berlin")
STATE_FILE = DATA / "scheduler_state.json"   # 每个任务上次在哪个时间点运行过
TICK = 20                 # 每隔几秒看一次时间
ON_TIME = 120             # 不补跑的任务：到点后这么多秒内才运行（容器重启后不会补发旧提醒）
BOT_RESTART_DELAY = 30    # 机器人退出后等几秒再重启

# name: 几点（hours）、几分（minute）、按顺序运行哪些脚本、错过了要不要补跑
JOBS: dict[str, dict] = {
    "mail":    {"hours": [1, 7, 13, 19], "minute": 30, "catch_up": True,
                "cmds": [["digest.py"], ["ilias_sync.py"]]},           # 邮件 + ILIAS
    "morning": {"hours": [7], "minute": 0, "catch_up": False,
                "cmds": [["remind.py", "--morning"]]},                 # 早上汇总
    "remind":  {"hours": list(range(7, 24)), "minute": 5, "catch_up": False,
                "cmds": [["remind.py"]]},                              # 3 小时内截止的提醒
}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(TZ):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 时间计算（纯函数，测试里直接调用）

def latest_slot(job: dict, now: dt.datetime) -> dt.datetime:
    """now 之前（含 now）最近的一个计划时间点。"""
    for back in (0, 1):
        day = (now - dt.timedelta(days=back)).date()
        for h in sorted(job["hours"], reverse=True):
            t = dt.datetime.combine(day, dt.time(h, job["minute"]), tzinfo=now.tzinfo)
            if t <= now:
                return t
    raise ValueError("时间表是空的")


def next_slot(job: dict, now: dt.datetime) -> dt.datetime:
    """now 之后最近的一个计划时间点。"""
    for ahead in (0, 1):
        day = (now + dt.timedelta(days=ahead)).date()
        for h in sorted(job["hours"]):
            t = dt.datetime.combine(day, dt.time(h, job["minute"]), tzinfo=now.tzinfo)
            if t > now:
                return t
    raise ValueError("时间表是空的")


def due(job: dict, now: dt.datetime, last: dt.datetime | None) -> dt.datetime | None:
    """现在该不该运行。该 → 返回这次对应的计划时间点；不该 → None。

    last 是上次运行对应的时间点；None 表示从来没运行过（第一次启动只记下时间，不运行，
    和 systemd 一样）。
    """
    slot = latest_slot(job, now)
    if last is not None and slot <= last:
        return None                                   # 这个时间点已经跑过了
    if job["catch_up"]:
        return slot if last is not None else None
    return slot if (now - slot).total_seconds() < ON_TIME else None


# ---------------------------------------------------------------- 运行

def load_state() -> dict[str, dt.datetime]:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {k: dt.datetime.fromisoformat(v) for k, v in raw.items()}
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, dt.datetime]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v.isoformat() for k, v in state.items()}, indent=1),
                   encoding="utf-8")
    tmp.replace(STATE_FILE)


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
        """按顺序运行一个任务的所有脚本；前一个失败也继续下一个（和 systemd 的 "-" 一样）。"""
        for cmd in JOBS[name]["cmds"]:
            if self.stopping.is_set():
                return
            log(f"{name}: 开始 {' '.join(cmd)}")
            p = subprocess.Popen([sys.executable, "-u", *cmd], cwd=HERE)
            with self.lock:
                self.procs.add(p)
            code = p.wait()
            with self.lock:
                self.procs.discard(p)
            log(f"{name}: {cmd[0]} 结束（退出码 {code}）")

    def start_job(self, name: str) -> bool:
        t = self.jobs.get(name)
        if t and t.is_alive():
            log(f"{name}: 上一次还没跑完，这次跳过")
            return False
        t = threading.Thread(target=self.run_job, args=(name,), daemon=True)
        self.jobs[name] = t
        t.start()
        return True

    def check_bot(self) -> None:
        if not self.with_bot or self.stopping.is_set():
            return
        if self.bot and self.bot.poll() is None:
            return                                    # 正在运行
        if self.bot:                                  # 刚发现它退出了
            log(f"bot: 退出了（退出码 {self.bot.returncode}），{BOT_RESTART_DELAY} 秒后重启")
            self.bot, self.bot_down_since = None, time.monotonic()
        if self.bot_down_since and time.monotonic() - self.bot_down_since < BOT_RESTART_DELAY:
            return
        log("bot: 启动")
        self.bot = subprocess.Popen([sys.executable, "-u", "bot.py"], cwd=HERE)
        self.bot_down_since = None

    def stop(self, *_args) -> None:
        if self.stopping.is_set():
            return
        log("收到停止信号，正在关闭")
        self.stopping.set()
        with self.lock:
            procs = list(self.procs)
        for p in procs + ([self.bot] if self.bot else []):
            if p.poll() is None:
                p.terminate()

    def loop(self) -> None:
        state = load_state()
        now = dt.datetime.now(TZ)
        for name, job in JOBS.items():               # 第一次启动：只记下时间点，不运行
            if name not in state:
                state[name] = latest_slot(job, now)
        save_state(state)
        log(f"调度器启动（数据文件夹 {DATA}），机器人：{'开' if self.with_bot else '关'}")
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
        log("已停止")


def main() -> int:
    ap = argparse.ArgumentParser(description="代替 systemd 的小调度器（Docker 用）")
    ap.add_argument("--no-bot", action="store_true", help="不开聊天机器人，只跑定时任务")
    ap.add_argument("--list", action="store_true", help="打印时间表然后退出")
    ap.add_argument("--run", choices=sorted(JOBS), help="马上运行某个任务一次")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.list:
        now = dt.datetime.now(TZ)
        for name, job in JOBS.items():
            cmds = " → ".join(" ".join(c) for c in job["cmds"])
            print(f"{name:8} {job['minute']:02d} 分，{job['hours']} 点  下次 "
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
