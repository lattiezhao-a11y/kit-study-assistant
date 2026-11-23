#!/usr/bin/env python3
"""
机器人自动测试（在树莓派上运行）：python3 tests/run_tests.py [--no-llm]

所有会写入的东西都用临时文件夹里的【副本】：deadlines.json、config.toml、todos、课表。
真实提醒和设置不会被改，也不发 Telegram。邮件、ILIAS 论坛只读。
  A 部分：直接调用每个工具（0 token）
  语言：中文 / 德语的固定文字、切换语言、按钮（0 token）
  B 部分：用一串中文句子测 AI 有没有选对工具，最后测用德语聊天和切换语言（花少量 token）
测试默认用中文（不管 config.toml 里现在是什么语言），德语的部分单独测。
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
import tomllib
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import digest  # noqa: E402

digest.load_env(digest.DATA / ".env")
import bot  # noqa: E402
import i18n  # noqa: E402
import ilias_sync  # noqa: E402
import tools  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="bottest-"))
for f in ("deadlines.json", "config.toml", "ilias_state.json"):
    if (digest.DATA / f).exists():
        shutil.copy2(digest.DATA / f, TMP / f)
ilias_sync.DEADLINES_FILE = TMP / "deadlines.json"
ilias_sync.LOCK_FILE = TMP / "deadlines.lock"
ilias_sync.STATE_FILE = TMP / "ilias_state.json"
tools.TODO_FILE = TMP / "todos.json"
tools.TIMETABLE_FILE = TMP / "timetable.json"
tools.CONFIG_PATH = TMP / "config.toml"
tools.BACKUP_DIR = TMP / "backup"
# Copies begin in Chinese so language-switch tests remain meaningful.
_cfg_text = tools.CONFIG_PATH.read_text(encoding="utf-8")
tools.CONFIG_PATH.write_text(re.sub(r'(?m)^language\s*=\s*"[^"]*"', 'language = "zh"', _cfg_text), encoding="utf-8")
CFG = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
tools.CFG.update(CFG)
ORIG_CONFIG = tools.CONFIG_PATH.read_text(encoding="utf-8")
i18n.LANG = "zh"                 # The following assertions use Chinese; German is tested separately in part_lang.

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, bool(ok), info))
    print(f"{'✅' if ok else '❌'} {name}" + (f"  —  {info}" if info and not ok else ""))


def call(name: str, **args) -> str:
    return bot.run_tool(name, json.dumps(args, ensure_ascii=False))


def show(text: str, n: int = 600) -> None:
    print("   " + text[:n].replace("\n", "\n   ") + ("…" if len(text) > n else ""))


# ================================================================ Formatting: Markdown → Telegram HTML
from html.parser import HTMLParser  # noqa: E402

ALLOWED = {"b", "i", "s", "code", "pre", "a"}


def valid_html(s: str) -> bool:
    """只用 Telegram 认识的标签，而且每个都正确闭合。"""
    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.ok = [], True

        def handle_starttag(self, tag, attrs):
            self.ok &= tag in ALLOWED
            self.stack.append(tag)

        def handle_endtag(self, tag):
            self.ok &= bool(self.stack) and self.stack.pop() == tag
    p = P()
    p.feed(s)
    p.close()
    return p.ok and not p.stack and "<" not in re.sub(r"</?(b|i|s|code|pre|a)\b[^>]*>", "", s)


def part_format() -> None:
    print("\n========== 格式转换（0 token）==========")
    cases = [
        ("**粗体** 和 *斜体*", "<b>粗体</b> 和 <i>斜体</i>"),
        ("## 今天的作业", "<b>今天的作业</b>"),
        ("- 第一条\n* 第二条", "• 第一条\n• 第二条"),
        ("用 `ls -l` 看", "用 <code>ls -l</code> 看"),
        ("```\nif a < b and c > d:\n    **不转换**\n```", "<pre>if a &lt; b and c &gt; d:\n    **不转换**</pre>"),
        ("看 [ILIAS](https://ilias.studium.kit.edu/a?x=1&y=2)",
         '看 <a href="https://ilias.studium.kit.edu/a?x=1&amp;y=2">ILIAS</a>'),
        ("3 < 5 & 7 > 2", "3 &lt; 5 &amp; 7 &gt; 2"),
        ("| 课 | 时间 |\n|---|---|\n| BS | 9:45 |", "课 | 时间\nBS | 9:45"),
        ("2 * 3 * 4 = 24", "2 * 3 * 4 = 24"),
        ("~~取消~~", "<s>取消</s>"),
        ("> 引用的话", "▎ 引用的话"),
        ("1. 第一\n2) 第二\n  20. 二十\n21. 二一", "① 第一\n② 第二\n  ⑳ 二十\n21. 二一"),
        ("截止 11/30 周一 13:15，共 3. 5 分", "截止 11/30 周一 13:15，共 3. 5 分"),
    ]
    for md, want in cases:
        got = bot.md_to_html(md)
        check(f"格式：{md[:25]!r}", got == want and valid_html(got), f"得到 {got!r}，应该是 {want!r}")
    long = "\n".join(f"- 第 {i} 行 **粗体**" for i in range(600))
    parts = bot.split_text(long, 3000)
    check("长消息按行切开，每段都不超长、格式完整",
          len(parts) > 1 and all(len(bot.md_to_html(x)) < 4096 and valid_html(bot.md_to_html(x))
                                 for x in parts))


# ================================================================ Telegram connection (getMe only; no messages)

def part_net() -> None:
    print("\n========== Telegram 连接（0 token，不发消息）==========")
    import socket
    import time as _t
    tg = bot.Telegram(digest.secret(CFG["telegram"]["bot_token_env"]))
    took = []
    for _ in range(5):
        t = _t.time()
        tg.call("getMe", http_timeout=10)
        took.append(_t.time() - t)
    first = tg.local.conn.sock
    tg.call("getMe", http_timeout=10)
    check("连接一直保持，不用每次重新建", tg.local.conn.sock is first,
          " ".join(f"{x:.2f}s" for x in took))
    print("   5 次 getMe：" + " ".join(f"{x:.2f}s" for x in took))
    tg.local.conn.sock.shutdown(socket.SHUT_RDWR)          # Simulate a peer closing the connection.
    try:
        ok = tg.call("getMe", http_timeout=10).get("is_bot")
    except Exception as e:
        ok = repr(e)
    check("连接被关掉后自动换新连接，照样成功", ok is True, str(ok))
    old_host, old_tries = bot.TG_HOST, bot.CONNECT_TRIES
    bot.TG_HOST, bot.CONNECT_TRIES = "10.255.255.1", 2      # An unreachable address.
    t = _t.time()
    try:
        tg._drop()
        tg.call("getMe")
        err = None
    except Exception as e:
        err = e
    spent = _t.time() - t
    bot.TG_HOST, bot.CONNECT_TRIES = old_host, old_tries
    check("「敲门」没反应时每次最多等 3 秒就放弃", isinstance(err, TimeoutError) and spent < 7.5,
          f"{err!r}，用了 {spent:.1f}s")
    tg._drop()


# ================================================================ Data directory and scheduler (Docker; zero tokens)

def part_scheduler() -> None:
    print("\n========== 数据文件夹 + 调度器（0 token）==========")
    import datetime as _dt
    import os
    import subprocess
    import scheduler
    import tempfile as _tf
    # DATA_DIR defaults to the source directory; Docker sets it explicitly.
    check("DATA_DIR 不设置 → 数据就在代码文件夹",
          "DATA_DIR" in os.environ or digest.DATA == HERE.resolve(), str(digest.DATA))
    with _tf.TemporaryDirectory() as d:
        out = subprocess.run([sys.executable, "-c", "import digest, tools, ilias_sync, bot;"
                              "print(digest.DATA, tools.TODO_FILE.parent, "
                              "ilias_sync.DEADLINES_FILE.parent, bot.STATE_FILE.parent)"],
                             cwd=HERE, env={**os.environ, "DATA_DIR": d},
                             capture_output=True, text=True)
        paths = out.stdout.split()
        check("DATA_DIR 设置了 → 所有数据文件都在那里",
              len(paths) == 4 and all(Path(p) == Path(d).resolve() for p in paths),
              out.stdout + out.stderr[-300:])

    tz = scheduler.TZ
    J = scheduler.JOBS

    def t(day: int, h: int, m: int, s: int = 0):
        return _dt.datetime(2026, 11, day, h, m, s, tzinfo=tz)

    due = scheduler.due
    check("调度：07:30 到点 → 跑邮件", due(J["mail"], t(24, 7, 30, 10), t(24, 1, 30)) == t(24, 7, 30))
    check("调度：同一个时间点不跑第二次", due(J["mail"], t(24, 7, 31), t(24, 7, 30)) is None)
    check("调度：容器关了一夜 → 启动后补跑最近一次邮件",
          due(J["mail"], t(24, 10, 0), t(23, 19, 30)) == t(24, 7, 30))
    check("调度：第一次启动不补跑", due(J["mail"], t(24, 10, 0), None) is None)
    check("调度：错过的 3 小时提醒不补发", due(J["remind"], t(24, 9, 20), t(24, 8, 5)) is None)
    check("调度：09:05 发 3 小时提醒", due(J["remind"], t(24, 9, 5, 30), t(24, 8, 5)) == t(24, 9, 5))
    check("调度：23:05 有提醒，00:05 没有",
          due(J["remind"], t(24, 23, 5), t(24, 22, 5)) == t(24, 23, 5)
          and due(J["remind"], t(25, 0, 5), t(24, 23, 5)) is None)
    check("调度：07:00 早上汇总", due(J["morning"], t(24, 7, 0, 20), t(23, 7, 0)) == t(24, 7, 0))
    check("调度：凌晨 01:30 的邮件检查跨天也算对",
          scheduler.latest_slot(J["mail"], t(25, 0, 10)) == t(24, 19, 30)
          and scheduler.next_slot(J["mail"], t(24, 20, 0)) == t(25, 1, 30))
    timers = {f.stem: f.read_text(encoding="utf-8") for f in (HERE / "deploy").glob("*.timer")}
    check("调度表和 deploy/*.timer 一致",
          "01,07,13,19:30:00" in timers["mail-digest"] and "07..23:05:00" in timers["remind"]
          and "07:00:00" in timers["morning-summary"]
          and J["mail"]["hours"] == [1, 7, 13, 19] and J["mail"]["minute"] == 30
          and J["remind"]["hours"] == list(range(7, 24)) and J["remind"]["minute"] == 5
          and J["morning"]["hours"] == [7] and J["morning"]["minute"] == 0)


# ================================================================ Offline regression checks

def part_regressions() -> None:
    import os
    import ssl
    from unittest.mock import patch
    import mail_imap
    import setup

    account = {"name": "test", "host": "imap.example.invalid", "user": "fixture",
               "password_env": "TEST_IMAP_PASSWORD"}
    with patch.object(mail_imap.imaplib, "IMAP4_SSL") as connect, \
            patch.dict(os.environ, {"TEST_IMAP_PASSWORD": "fixture"}):
        conn = connect.return_value
        conn.select.return_value = ("OK", [])
        conn.response.return_value = ("UIDVALIDITY", [b"1"])
        conn.uid.return_value = ("OK", [b""])
        digest.fetch_account(account, {}, 1, 10, 100)
        tools._close(tools._imap(account))
        setup.check_imap(account["host"], account["user"], "fixture")
        contexts = [c.kwargs["ssl_context"] for c in connect.call_args_list]
        check("三个 IMAP 入口都验证证书和主机名", len(contexts) == 3 and all(
            ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname for ctx in contexts))

    course, old_day, new_day = "Fixture course", "2099-01-02", "2099-01-03"
    with patch.object(ilias_sync, "DEADLINES_FILE", TMP / "regression_deadlines.json"):
        call("ddl_add", course=course, title="Task A", date=old_day)
        other = call("ddl_add", course=course, title="Task B", date=old_day)
        repeat = call("ddl_add", course=course, title="task  a", date=old_day, time="09:00")
        with ilias_sync.locked_store(save=False) as store:
            first = next(d for d in store if d["title"] == "Task A")
            check("同一天的不同作业分别保存，同名作业补上时间", len(store) == 2
                  and other.startswith("已添加") and "没有重复添加" in repeat
                  and first["due"][11:16] == "09:00")
        call("ddl_edit", id=first["id"], title="Renamed A", date=new_day, time="none")
        duplicate = call("ddl_add", course=course, title="Task A", date=old_day, time="09:00")
        with ilias_sync.locked_store(save=False) as store:
            first = next(d for d in store if d["title"] == "Renamed A")
            check("旧标题和旧日期仍能去重，原截止时间不会覆盖手动改期", len(store) == 2
                  and "没有重复添加" in duplicate and first["due"].startswith(new_day)
                  and not first["time_known"])

        call("ddl_add", course=course, title="Task C", date=old_day)
        mail = digest.Mail("KIT", "Fixture", "Task B", "", False, True, cat="must",
                           course=course, deadline=new_day, replaces=old_day)
        digest.add_mail_deadlines([mail], save=True)
        with ilias_sync.locked_store(save=False) as store:
            check("邮件改期只划掉匹配的旧作业", mail.reminder == "added" and len(store) == 4
                  and [d["title"] for d in store if d.get("done")] == ["Task B"])
        digest.add_mail_deadlines([mail], save=True)
        with ilias_sync.locked_store(save=False) as store:
            check("重复处理改期邮件不影响其他作业", mail.reminder == "dup" and len(store) == 4
                  and [d["title"] for d in store if d.get("done")] == ["Task B"])


# ================================================================ A: direct tool calls
def part_a() -> None:
    print("\n========== A：直接调用工具（0 token）==========")
    # O1
    out = call("ddl_list")
    show(out, 400)
    check("ddl_list 列出编号", re.search(r"^#\d+ ", out, re.M))
    with ilias_sync.locked_store(save=False) as store:
        n_active = len(ilias_sync.upcoming(store))
    shown = len(re.findall(r"^#\d+ ", out, re.M))
    hidden = sum(int(n) for n in re.findall(r"(?:还没发布的作业|考试) (\d+) 个", out))
    full = call("ddl_list", all=True)
    check("默认只列已发布的作业，没发布的和考试只说个数",
          shown + hidden == n_active and len(re.findall(r"^#\d+ ", full, re.M)) == n_active, out[-300:])
    week = call("ddl_list", this_week=True)
    sunday = (tools.now().date() + __import__("datetime").timedelta(days=6 - tools.now().weekday()))
    days_in_week = [(int(m), int(d)) for m, d in re.findall(r"— (\d+)/(\d+) 周", week)]
    check("this_week 只到这周日", "这周，到" in week and all(
        (m, d) <= (sunday.month, sunday.day) for m, d in days_in_week), week[:300])
    pub = {"GKI": [1, 2]}
    check("发布判断：有发布日期看日期，没有看 ILIAS 里的编号",
          tools.released({"source": "ilias", "title": "Übung 4", "course": "GKI", "release": "2099-01-01"}, pub) is False
          and tools.released({"source": "ilias", "title": "Übung 3", "course": "GKI", "release": "2000-01-01"}, pub)
          and tools.released({"source": "ilias", "title": "Übung 2 Deadline", "course": "GKI"}, pub)
          and not tools.released({"source": "ilias", "title": "Übung 5 Deadline", "course": "GKI"}, pub)
          and tools.released({"source": "ilias", "title": "Übung 5", "course": "TGI"}, pub)
          and tools.released({"source": "manual", "title": "Blatt 9", "course": "GKI"}, pub))
    out = call("ddl_add", course="Robotics I", title="测试作业", date="2026-12-01", time="10:00")
    m = re.search(r"#(\d+)", out)
    check("ddl_add 新增", out.startswith("已添加") and m, out)
    tid = int(m.group(1)) if m else 0
    check("ddl_add 重复不加", "没有重复添加" in call("ddl_add", course="Robotics I", title="测试作业",
                                                   date="2026-12-01"))
    out = call("ddl_edit", id=tid, date="2026-12-03")
    check("ddl_edit 推迟", "12/3" in out, out)
    with ilias_sync.locked_store() as store:
        again = ilias_sync.merge(store, [{"course": "Robotics I", "title": "测试作业",
                                          "due": "2026-12-01T10:00+01:00", "time_known": True}])
    check("推迟后旧日期不会被 ILIAS 再加回来", not again)
    check("ddl_done 标记交了", "已标记为交了" in call("ddl_done", id=tid))
    check("交了以后不在列表里", f"#{tid} " not in call("ddl_list"))
    check("ddl_done undo 恢复", "已恢复" in call("ddl_done", id=tid, undo=True)
          and f"#{tid} " in call("ddl_list"))
    check("ddl_delete 删除", "已删除" in call("ddl_delete", id=tid) and f"#{tid} " not in call("ddl_list"))
    check("错误编号给出提示", "没有编号" in call("ddl_done", id=99999))
    check("错误日期给出提示", "YYYY-MM-DD" in call("ddl_add", course="a", title="b", date="下周五"))

    # O2
    out = call("todo_add", text="去银行开户", date="2026-11-25", time="10:30")
    check("todo_add", out.startswith("已记下") and "10:30" in out, out)
    import remind
    remind.TODO_FILE = tools.TODO_FILE
    items = remind.todo_items()
    check("有日期的待办会进提醒", len(items) == 1 and items[0]["due"].startswith("2026-11-25T10:30")
          and items[0]["time_known"], str(items))
    check("todo_list", "去银行开户" in call("todo_list"))
    check("todo_done", "已完成" in call("todo_done", id=1) and "去银行" not in call("todo_list"))
    check("todo_delete", "已删除" in call("todo_delete", id=1))

    # O5
    out = call("timetable_add", weekday=1, start="9:45", end="11:15", course="Betriebssysteme",
               kind="讲座", room="HS a.m. Fasanengarten")
    check("timetable_add", "每周一 09:45–11:15" in out, out)
    out = call("schedule", date="2026-11-30", days=2)
    show(out, 500)
    check("schedule 有课表和日期", "11/30 周一" in out and "Betriebssysteme" in out, out)
    check("timetable_list / remove", "课#1" in call("timetable_list")
          and "已从课表删除" in call("timetable_remove", id=1))
    tools.save_json(tools.TODO_FILE, [])
    out = call("schedule")
    check("schedule 今天（读 ILIAS 日历）", "失败" not in out, out)

    # O4
    out = call("settings_show")
    check("settings_show", "always_ignore" in out and "quiet_hours" in out, out)
    n_comments = ORIG_CONFIG.count("#")
    steps = [dict(key="always_ignore", action="add", value="测试规则：所有来自 example.com 的邮件"),
             dict(key="always_important_senders", action="add", value="tutor@kit.edu"),
             dict(key="quiet_hours", action="set", value="23,7"),
             dict(key="forum_hour", action="set", value="7"),
             dict(key="job_search", action="set", value="true")]
    for st in steps:
        out = call("settings_change", **st)
        ok_pending = "还没生效" in out and tools.PENDING.get("settings")
        unchanged = tools.CONFIG_PATH.read_text(encoding="utf-8") == ORIG_CONFIG \
            if st is steps[0] else True
        check(f"settings_change {st['key']} 只是提议", ok_pending and unchanged, out)
        try:
            msg = tools.apply_pending()
            check(f"确认后改好 {st['key']}", msg.startswith("✅"), msg)
        except Exception as e:
            check(f"确认后改好 {st['key']}", False, repr(e))
    new = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
    exp = copy.deepcopy(CFG)
    exp["llm"]["always_ignore"] = CFG["llm"]["always_ignore"] + ["测试规则：所有来自 example.com 的邮件"]
    exp.setdefault("safety_net", {})["always_important_senders"] = \
        CFG.get("safety_net", {}).get("always_important_senders", []) + ["tutor@kit.edu"]
    exp["ilias"]["quiet_hours"], exp["ilias"]["forum_hour"] = [23, 7], 7
    exp.setdefault("job", {})["job_search"] = True
    check("config.toml 只改了这 5 项", new == exp)
    check("注释都还在", tools.CONFIG_PATH.read_text(encoding="utf-8").count("#") >= n_comments)
    check("每次改动前都有备份", len(list(tools.BACKUP_DIR.glob("config.toml.*"))) >= 1)
    # Change it back.
    for st in [dict(key="always_ignore", action="remove", value=str(len(exp["llm"]["always_ignore"]))),
               dict(key="always_important_senders", action="remove", value="tutor@kit.edu"),
               dict(key="quiet_hours", action="set", value="0,7"),
               dict(key="forum_hour", action="set", value=str(CFG["ilias"].get("forum_hour", 19))),
               dict(key="job_search", action="set", value="false")]:
        call("settings_change", **st)
        if tools.PENDING.get("settings"):
            tools.apply_pending()
    back = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
    check("改回去以后和原来的设置一样", all(
        back.get(s, {}).get(k) == CFG.get(s, {}).get(k)
        for k, (s, *_) in tools.SETTINGS.items() if k in CFG.get(s, {})))
    check("不能改的设置被拒绝", "工具出错" in call("settings_change", key="password", action="set", value="x"))
    tools.CONFIG_PATH.write_text(ORIG_CONFIG, encoding="utf-8")
    tools.CFG.clear(), tools.CFG.update(CFG)

    # Add and remove about_me one line at a time; the “not interested” preference is learned here.
    old_me = CFG["llm"].get("about_me", "")
    out = call("settings_change", key="about_me", action="add", value="不感兴趣：测试用的一类东西")
    pv = tools.PENDING.get("settings", {}).get("preview", "")
    check("about_me add 只是提议，预览里有新的一行和说明",
          "还没生效" in out and "不感兴趣：测试用的一类东西" in pv and "⚪ 忽略" in pv, pv)
    tools.apply_pending()
    me = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))["llm"]["about_me"]
    check("about_me 加在最后一行，原来的内容都还在",
          me.splitlines()[-1] == "不感兴趣：测试用的一类东西" and all(
              ln.strip() in me for ln in old_me.splitlines() if ln.strip()), me)
    check("settings_show 逐行编号显示 about_me", "不感兴趣：测试用的一类东西" in call("settings_show"))
    check("about_me 重复的一行不加", "已经有了" in call(
        "settings_change", key="about_me", action="add", value="不感兴趣：测试用的一类东西"))
    call("settings_change", key="about_me", action="remove", value="测试用的一类")
    tools.apply_pending()
    me = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))["llm"].get("about_me", "")
    check("about_me 按内容删掉一行后和原来一样", tools._lines(me) == tools._lines(old_me), me)
    tools.CONFIG_PATH.write_text(ORIG_CONFIG, encoding="utf-8")
    tools.CFG.clear(), tools.CFG.update(CFG)

    # Removing a mail-derived reminder suggests “not interested”; manual items do not.
    with ilias_sync.locked_store() as store:
        tools._ensure_ids(store)
        store.append({"course": "📧 测试项目", "title": "测试：跨校短期课程申请",
                      "due": "2099-01-05T00:00+01:00", "time_known": False, "source": "mail"})
        tools._ensure_ids(store)
        mid_ = store[-1]["id"]
    out = call("ddl_delete", id=mid_)
    check("删除邮件来的提醒时提示 AI 学「不感兴趣」", "已删除" in out and "key=about_me" in out, out)
    out = call("ddl_add", course="Robotics I", title="测试作业2", date="2099-01-06")
    out = call("ddl_delete", id=int(re.search(r"#(\d+)", out).group(1)))
    check("删除手动加的不提示", "已删除" in out and "about_me" not in out, out)

    # Email classification: duties add reminders, opportunities do not, and about_me enters the prompt.
    prompt, _ = digest.build_prompt({"about_me": "我是学生\n不感兴趣：短期交流项目"}, {})
    check("分类提示词里有 about_me 的每一行、不感兴趣规则和 kind",
          "不感兴趣：短期交流项目" in prompt and "一律归为 ignore" in prompt
          and '"kind":"duty|chance"' in prompt, prompt[:300])

    def mk(subject, kind):
        return digest.Mail("KIT", "Test <t@kit.edu>", subject, "", False, True, cat="must",
                           summary=subject, deadline="2099-02-01", kind=kind)
    duty, chance = mk("测试：考试报名", "duty"), mk("测试：交流项目申请", "chance")
    digest.add_mail_deadlines([duty, chance], save=False)
    check("义务的截止日期加进提醒，机会的不加", duty.reminder == "added" and chance.reminder == "chance",
          f"{duty.reminder} / {chance.reminder}")
    text = digest.build_digest([duty, chance], [], 0)
    check("摘要里机会显示「可选，没加提醒」", "已加入提醒" in text and "可选，截止 02-01（没加提醒" in text, text)
    with ilias_sync.locked_store(save=False) as store:
        check("save=False 时没写进 deadlines.json", not any("测试：" in d["title"] and d.get("source") == "mail"
                                                           and not d.get("done") for d in store))

    # O3
    out = call("mail_list", days=2)
    show(out, 700)
    check("mail_list", "最近 2 天" in out and "连接失败" not in out, out)
    mid = re.search(r"^(\w+:\d+) \|", out, re.M)
    if mid:
        out = call("mail_read", id=mid.group(1))
        show(out, 500)
        check("mail_read", out.startswith("发件人："), out)
    else:
        check("mail_read（最近 2 天没有邮件，跳过）", True)
    check("mail_read 格式错误给提示", "格式" in call("mail_read", id="abc"))

    # O6: create the forum list in the copy; real data is generated by the next ILIAS check.
    state = tools.load_json(ilias_sync.STATE_FILE, {})
    if not state.get("forums"):
        il = tools._ilias()
        il.pages = -400                    # Allow additional page requests during testing.
        fs: dict = {}
        skip = re.compile(CFG["ilias"]["skip_folders"], re.I) if CFG["ilias"].get("skip_folders") else None
        for c in CFG["ilias"]["courses"]:
            ilias_sync.crawl(il, c, copy.deepcopy(state.get("seen", {})), skip, {}, fs)
        state["forums"] = fs
        tools.save_json(ilias_sync.STATE_FILE, state)
        print(f"   （副本里生成了论坛列表：{len(fs)} 个论坛）")
    out = call("forum_recent", days=14)
    show(out, 600)
    check("forum_recent", "工具出错" not in out, out)
    tid = re.search(r"^(\d+/\d+) \|", out, re.M)
    if tid:
        out = call("forum_read", thread=tid.group(1))
        show(out, 500)
        check("forum_read", out.startswith("（以下是论坛原文"), out)


# ================================================================ Languages: Chinese / German (zero tokens)
CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff01-\uff5e]")    # Chinese characters and punctuation.


def no_chinese(s: str) -> bool:
    """德语界面里不能有汉字（选语言按钮上的「中文」两个字除外）。"""
    return not CJK.search(s.replace("中文", ""))


def german(s: str) -> bool:
    """AI 的回答是不是德语：汉字很少，而且有常见的德语词。"""
    return (len(CJK.findall(s)) <= len(s) * 0.15
            and re.search(r"\b(ich|du|dir|die|der|das|und|ist|sind|noch|nicht|keine?|auf|jetzt|Deutsch)\b",
                          s, re.I) is not None)


def restore_config() -> None:
    tools.CONFIG_PATH.write_text(ORIG_CONFIG, encoding="utf-8")
    tools.CFG.clear(), tools.CFG.update(CFG)
    tools.PENDING.clear()
    i18n.LANG = "zh"


def part_lang() -> None:
    print("\n========== 语言：中文 / 德语（0 token）==========")
    import datetime as _dt
    import string
    import forums
    import remind
    fields = lambda s: sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)   # noqa: E731
    bad = [k for k, v in i18n.TEXTS.items() if set(v) != {"zh", "de"} or fields(v["zh"]) != fields(v["de"])]
    check("每句固定文字都有中文和德语，而且要填的内容一样", not bad, str(bad))
    bad = [k for k, v in i18n.TEXTS.items() if not k.startswith("ai.") and not no_chinese(v["de"])]
    check("德语版里没有汉字", not bad, str(bad))
    check("每个能改的设置都有德语说明", set(i18n.SETTING_DESC_DE) == set(tools.SETTINGS))
    check("没写语言 / 写错了 → 中文", i18n.lang_of({}) == "zh" and i18n.lang_of({"general": {"language": "fr"}}) == "zh"
          and i18n.lang_of({"general": {"language": "DE"}}) == "de")
    check("德语里有「确认」的说法", {"ja", "bestätigen"} <= bot.CONFIRM_WORDS)

    i18n.LANG = "de"
    d = _dt.date(2026, 11, 30)
    check("德语日期：Mo 30.11. 13:15",
          i18n.day_label(d) == "Mo 30.11."
          and i18n.due_label(_dt.datetime(2026, 11, 30, 13, 15), True) == "Mo 30.11. 13:15"
          and i18n.date_text("2026-12-01") == "01.12.2026" and i18n.date_text("2026-12-01", True) == "1.12."
          and i18n.date_text("bald") == "bald",
          i18n.due_label(_dt.datetime(2026, 11, 30, 13, 15), True))
    # Deliveries: email digest, morning summary, three-hour reminders, ILIAS, and forums.
    mails = [digest.Mail("KIT", "Prof <p@kit.edu>", "Klausuranmeldung", "", False, True, cat="must",
                         summary="Anmeldung bis Freitag", deadline="2099-02-01", time="12:00", reminder="added"),
             digest.Mail("KIT", "Intl <i@kit.edu>", "Summer School", "", False, True, cat="maybe",
                         summary="Bewerbung offen", deadline="2099-03-01", kind="chance", reminder="chance"),
             digest.Mail("Gmail", "Shop <s@x.de>", "Black Friday", "", True, True, cat="ignore"),
             digest.Mail("Gmail", "X <x@y.de>", "", "", False, False)]
    text = digest.build_digest(mails, ["Gmail: Abruf fehlgeschlagen: Timeout"], 1234)
    show(text, 500)
    check("德语邮件摘要", no_chinese(text) and "Zu erledigen" in text and "01.02.2099 12:00" in text
          and "Frist 1.3." in text and "Ignoriert" in text and "(kein Betreff)" in text, text)
    now = ilias_sync.now()
    store = [{"course": "BS", "title": "Blatt 3", "due": (now + _dt.timedelta(hours=2)).isoformat(timespec="minutes"),
              "time_known": True},
             {"course": i18n.tr("rm.todo"), "title": "Bank", "due": (now + _dt.timedelta(days=2)).isoformat(
                 timespec="minutes"), "time_known": False}]
    text = remind.morning(store) + "\n" + remind.urgent(copy.deepcopy(store), [0, 0])
    show(text, 400)
    check("德语早上汇总和 3 小时提醒", no_chinese(text) and "fällig" in text and "(ohne Uhrzeit)" in text
          and "To-do" in text, text)
    text = ilias_sync.format_list(store, i18n.tr("il.new"))
    check("德语 ILIAS 推送", no_chinese(text) and "noch 1 Std." in text and "Blatt 3" in text, text)
    text = forums.build_message([("GKI", "Frage zu Blatt 2", 3, True)], {0: "Abgabe verschoben"}, 99)
    check("德语论坛总结", no_chinese(text) and "3 neue Beiträge, mit Antwort von Lehrenden" in text, text)
    text = bot.help_text() + bot.usage_text({"usage": {}})
    check("德语使用说明和 token 用量", no_chinese(text) and "/language" in text, text[:300])
    prompt, _ = digest.build_prompt({"about_me": "Kein Interesse: Hackathons"}, {})
    check("德语时 AI 用德语写邮件摘要", "德语" in prompt and "Kein Interesse" in prompt, prompt[-300:])
    call("settings_change", key="always_important_senders", action="add", value="tutor@kit.edu")
    pv = (tools.PENDING.get("settings") or {}).get("preview", "")
    check("德语改设置预览", no_chinese(pv) and "Vorher:" in pv and "tutor@kit.edu" in pv, pv)
    tools.PENDING.clear()
    i18n.LANG = "zh"

    # Language switch: update only config.toml's language entry, preserve comments, and make a backup.
    n_backup = len(list(tools.BACKUP_DIR.glob("config.toml.*"))) if tools.BACKUP_DIR.exists() else 0
    changed = tools.set_language("de")
    new = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
    exp = copy.deepcopy(CFG)
    exp.setdefault("general", {})["language"] = "de"
    check("切换到德语：config 里只多了 language = de，马上生效",
          changed and new == exp and i18n.LANG == "de" and tools.CFG == exp)
    check("切换语言时注释都还在、改之前有备份",
          tools.CONFIG_PATH.read_text(encoding="utf-8").count("#") >= ORIG_CONFIG.count("#")
          and len(list(tools.BACKUP_DIR.glob("config.toml.*"))) > n_backup)
    check("已经是德语再切一次：不改", tools.set_language("de") is False)
    out = call("language_set", language="zh")
    check("language_set 工具切回中文", "已切换为中文" in out and i18n.LANG == "zh"
          and tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))["general"]["language"] == "zh", out)
    check("不支持的语言被拒绝", "工具出错" in call("language_set", language="fr") and i18n.LANG == "zh")

    # Buttons: fake Telegram sends Chinese and German choices without delivering messages.
    class FakeTG:
        def __init__(self):
            self.calls, self.sent = [], []

        def call(self, method, http_timeout=30, **params):
            self.calls.append((method, params))
            return True

        def send(self, chat_id, text):
            self.sent.append(text)
    tg = FakeTG()
    bot.ask_language(tg, "1")
    btns = [b["callback_data"] for b in tg.calls[0][1]["reply_markup"]["inline_keyboard"][0]]
    check("/start 发出两个语言按钮", btns == ["lang:zh", "lang:de"] and tg.calls[0][1]["text"] == i18n.PICK, str(btns))
    tg = FakeTG()
    history = [{"role": "user", "content": "你好"}]
    cq = {"id": "q1", "data": "lang:de", "message": {"message_id": 7, "chat": {"id": 1, "type": "private"}}}
    bot.on_button(tg, "1", cq, history)
    methods = [m for m, _ in tg.calls]
    menu = next((p["commands"] for m, p in tg.calls if m == "setMyCommands"), [])
    check("点【Deutsch】：马上切换、清空对话、按钮那条改成「✅ Sprache: Deutsch」、发德语说明、菜单换成德语",
          i18n.LANG == "de" and not history and "answerCallbackQuery" in methods
          and ("editMessageText", {"chat_id": "1", "message_id": 7, "text": "✅ Sprache: Deutsch"}) in tg.calls
          and tg.sent and tg.sent[0].startswith("Ich bin dein Lernassistent")
          and [c["command"] for c in menu] == list(bot.COMMANDS) and all(no_chinese(c["description"]) for c in menu),
          f"{tg.calls} / {tg.sent[:1]}")
    tg = FakeTG()
    bot.on_button(tg, "1", dict(cq, data="lang:xx"), history)
    check("不认识的按钮：什么都不改", i18n.LANG == "de" and not tg.sent)
    restore_config()


# ================================================================ B: AI tool selection
CASES = [  # (user message, required tool, follows prior conversation, required reply text)
    ("还有哪些作业没交？", {"ddl_list"}, False, ""),
    ("BS 第三次作业交了", {"ddl_done"}, False, ""),
    ("撤销，刚才那个其实还没交", {"ddl_done"}, True, ""),
    ("TGI 的作业推迟到 12 月 2 号中午 12 点", {"ddl_edit"}, False, ""),
    ("加一个作业：Robotics 第 4 次作业，12 月 5 号 14:00 截止", {"ddl_add"}, False, ""),
    ("删掉刚才加的那个 Robotics 作业", {"ddl_delete"}, True, ""),
    ("这周有哪些作业要交？", {"ddl_list"}, False, ""),
    ("记一下：周三去银行开户", {"todo_add"}, False, ""),
    ("我有哪些待办？", {"todo_list"}, False, ""),
    ("银行那件事办完了", {"todo_done"}, True, ""),
    ("最近两天 KIT 邮箱有什么邮件？", {"mail_list"}, False, ""),
    ("第一封具体写了什么？", {"mail_read"}, True, ""),
    ("帮我回复这封邮件，说我收到了", set(), True, "不"),
    ("周一 9:45 到 11:15 有 BS 讲座，在 HS a.m. Fasanengarten", {"timetable_add"}, False, ""),
    ("下周一有什么安排？", {"schedule"}, False, ""),
    ("GKI 论坛最近在讨论什么？", {"forum_recent"}, False, ""),
    ("以后 Typeless 的邮件都忽略", {"settings_change"}, False, ""),
    ("删掉那个 Summer School 申请的提醒", {"ddl_delete", "settings_change"}, False, ""),
    ("像黑客松这种编程比赛我都不感兴趣，以后别提醒我", {"settings_change"}, False, ""),
    ("把不发提醒的时间改成晚上 23 点到早上 7 点", {"settings_change"}, False, ""),
    ("什么是页表？一句话回答", set(), False, ""),
    ("哪些作业没交", {"ddl_list"}, False, ""),
    ("把全部作业和考试都列出来", {"ddl_list"}, False, ""),
]


def part_b() -> None:
    print("\n========== B：AI 选工具（花 token）==========")
    state = {"usage": {}}
    history: list[dict] = []
    calls: list[tuple[str, dict]] = []          # Record arguments for every tool call.
    real_run = bot.run_tool

    def traced(name, raw):
        calls.append((name, json.loads(raw or "{}")))
        return real_run(name, raw)
    bot.run_tool = traced
    # Begin from a fixed state: the third BS assignment is unsubmitted.
    with ilias_sync.locked_store() as store:
        for d in store:
            if d["course"] == "Betriebssysteme" and "03" in d["title"]:
                for k in ("done", "done_at", "deleted"):
                    d.pop(k, None)
        tools._ensure_ids(store)                # Mail-added opportunity used to test learning after deletion.
        store.append({"course": "📧 KIT International", "title": "Summer School 2027 申请截止",
                      "due": "2099-03-01T00:00+01:00", "time_known": False, "source": "mail"})
        tools._ensure_ids(store)
    for text, need, keep, must in CASES:
        if not keep:
            history = []
        tools.PENDING.clear()
        used: list[str] = []
        try:
            calls.clear()
            reply = bot.answer(text, history, tools.CFG, state, trace=used)
        except Exception as e:
            traceback.print_exc()
            check(f"「{text}」", False, repr(e))
            continue
        ok = need <= set(used) and (need or not (set(used) - {"ddl_list", "todo_list", "mail_list"}))
        ok = ok and (must in reply)
        ok = ok and valid_html(bot.md_to_html(reply))
        lists = [c for n, c in calls if n == "ddl_list"]
        if text in ("还有哪些作业没交？", "哪些作业没交"):            # Normal query: not all assignments and not limited to this week.
            ok = ok and lists and not any(c.get("all") or c.get("this_week") for c in lists)
        if text == "这周有哪些作业要交？":
            ok = ok and any(c.get("this_week") for c in lists) and not any(c.get("all") for c in lists)
        if text == "把全部作业和考试都列出来":
            ok = ok and any(c.get("all") for c in lists)
        ok = ok and not re.search(r"#\d|KIT:\d|Gmail:\d|\d{6,}/\d{5,}", reply)   # Do not expose identifiers.
        if "settings_change" in need:
            ok = ok and bool(tools.PENDING.get("settings")) and \
                tools.CONFIG_PATH.read_text(encoding="utf-8") == ORIG_CONFIG
        if "不感兴趣" in text or "Summer School" in text:   # Write learned preferences to about_me as “not interested”.
            p = tools.PENDING.get("settings") or {}
            row = (tools._lines(p.get("new", "")) or [""])[-1]
            ok = ok and p.get("key") == "about_me" and row.startswith("不感兴趣")
            show(f"提议加的一行：{row}", 120)
        check(f"「{text}」→ {used or '不用工具'}", ok, f"需要 {need or '不用工具'}；回答：{reply[:200]}")
        show("回答：" + reply, 220)
    u = state["usage"]
    tin = sum(d["in"] for d in u.values())
    tout = sum(d["out"] for d in u.values())
    n_calls = sum(d["calls"] for d in u.values())
    print(f"\nB 部分共 {n_calls} 次 AI 调用，{tin + tout:,} token，"
          f"约 ${(tin * bot.PRICE_IN + tout * bot.PRICE_OUT) / 1e6:.3f}")
    check("AI 没有自己改掉设置（真正修改要我回复「确认」）",
          tools.CONFIG_PATH.read_text(encoding="utf-8") == ORIG_CONFIG)

    # Switch language in chat immediately, converse in German, then switch back.
    print("\n   —— 语言 ——")
    lang_cases = [  # (user message, expected language afterwards, required tool)
        ("我要用德语版", "de", {"language_set"}),
        ("Welche Abgaben sind noch offen?", "de", {"ddl_list"}),
        ("Bitte wieder auf Chinesisch antworten", "zh", {"language_set"}),
    ]
    try:
        for text, lang, need in lang_cases:
            used = []
            try:
                calls.clear()
                reply = bot.answer(text, [], tools.CFG, state, trace=used)
            except Exception as e:
                traceback.print_exc()
                check(f"「{text}」", False, repr(e))
                continue
            conf = tomllib.loads(tools.CONFIG_PATH.read_text(encoding="utf-8"))
            ok = need <= set(used) and i18n.LANG == lang and i18n.lang_of(conf) == lang
            ok = ok and (german(reply) if lang == "de" else bool(CJK.search(reply)))
            ok = ok and not re.search(r"#\d|KIT:\d|Gmail:\d|\d{6,}/\d{5,}", reply)
            if "ddl_list" in need:
                lists = [c for n, c in calls if n == "ddl_list"]
                ok = ok and lists and not any(c.get("all") or c.get("this_week") for c in lists)
            check(f"「{text}」→ {used or '不用工具'}，之后是 {lang}", ok,
                  f"需要 {need}；现在 {i18n.LANG}；回答：{reply[:200]}")
            show("回答：" + reply, 220)
    finally:
        restore_config()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        part_format()
        part_scheduler()
        part_regressions()
        if "--format-only" not in sys.argv:
            part_net()
            part_a()
            part_lang()
            if "--no-llm" not in sys.argv:
                part_b()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n========== 结果：{len(results) - len(bad)}/{len(results)} 通过 ==========")
    for name, _, info in bad:
        print(f"❌ {name}\n   {info[:300]}")
    sys.exit(1 if bad else 0)
