#!/usr/bin/env python3
"""Interactive setup wizard that generates config.toml and a mode-600 .env file.

The default mode handles initial setup, --courses replaces only courses for a new
semester, and --no-check skips network validation for testing. Values are validated
as entered, but files are written only after every question is answered.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import re
import shutil
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import i18n
import mail_imap
from common import DATA

HERE = Path(__file__).resolve().parent
CONFIG = DATA / "config.toml"
ENV = DATA / ".env"
BACKUP_DIR = DATA / "backup"
EXAMPLE = HERE / "config.example.toml"

# ---------------------------------------------------------------- Text
# Wizard text is stored in i18n.py under keys beginning with “su.”, with Chinese and German variants.

def tr(key: str, /, **kw) -> str:
    return i18n.tr("su." + key, **kw)


# ---------------------------------------------------------------- Input

def _clean(s: str) -> str:
    return "".join(ch for ch in s if ch >= " " and ch != "\x7f").strip()


def ask(prompt: str, default: str = "", required: bool = False) -> str:
    hint = f" {tr('default', d=default)}" if default else ""
    while True:
        v = _clean(input(f"{prompt}{hint} "))
        if v:
            return v
        if default:
            return default
        if not required:
            return ""
        print(tr("required"))


def ask_secret(prompt: str, required: bool = True) -> str:
    while True:
        # Hide piped input in a terminal; read it normally when tests provide answers through a pipe.
        v = getpass.getpass(prompt + " ") if sys.stdin.isatty() else input(prompt + " ")
        v = _clean(v)
        if v or not required:
            return v
        print(tr("required"))


def yes(prompt: str, default: bool = True) -> bool:
    v = input(f"{prompt} {tr('yes_no' if default else 'no_yes')} ").strip().lower()
    if not v:
        return default
    return v[0] in "yj是好"


def menu(prompt: str, options: list[str]) -> int:
    print(prompt)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    while True:
        v = input(tr("choose") + " ").strip()
        if v.isdigit() and 1 <= int(v) <= len(options):
            return int(v) - 1
        print(tr("bad_choice"))


def parse_numbers(text: str, n: int) -> list[int] | None:
    """Parse one-based numbers such as “1 3, 4”; return None for values outside 1..n."""
    parts = [p for p in re.split(r"[\s,，、;]+", text.strip()) if p]
    if not all(p.isdigit() and 1 <= int(p) <= n for p in parts):
        return None
    return list(dict.fromkeys(int(p) for p in parts))


def title(key: str) -> None:
    print(f"\n━━━━ {tr(key)} ━━━━")


# ---------------------------------------------------------------- Network checks (never called with --no-check)

def check_imap(host: str, user: str, password: str, port: int = 993) -> None:
    conn = mail_imap.connect(host, port, timeout=30)
    try:
        conn.login(user, password)
        typ, _ = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError("INBOX")
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def check_llm(base_url: str, key: str) -> None:
    """Check an API key through GET /models without consuming tokens."""
    req = urllib.request.Request(base_url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(tr("llm.bad_key") if e.code == 401 else f"HTTP {e.code}") from None


def tg_call(token: str, method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(params).encode() if params else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}
        return {"ok": False, "error_code": e.code, "description": body.get("description", str(e))}


def extract_chat_id(updates: dict) -> int | None:
    """Return the chat ID from the latest private message in a getUpdates result."""
    for u in reversed(updates.get("result", [])):
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private" and "id" in chat:
            return int(chat["id"])
    return None


def wait_for_chat(token: str, seconds: int = 120) -> int | None:
    """Wait for a user message and return its chat ID; raise RuntimeError("busy") if the bot runs elsewhere."""
    end = time.time() + seconds
    offset = None
    while time.time() < end:
        params = {"timeout": 20, "allowed_updates": ["message"]}
        if offset:
            params["offset"] = offset
        r = tg_call(token, "getUpdates", **params)
        if not r.get("ok"):
            if r.get("error_code") == 409:
                raise RuntimeError("busy")
            raise RuntimeError(r.get("description", "getUpdates"))
        cid = extract_chat_id(r)
        if cid:
            return cid
        if r.get("result"):
            offset = r["result"][-1]["update_id"] + 1
    return None


# ---------------------------------------------------------------- Write configuration

def q(v) -> str:
    """Convert a Python value to TOML; TOML accepts JSON string notation."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(q(x) for x in v) + "]"
    raise TypeError(type(v))


def render_courses(courses: list[dict]) -> str:
    out = []
    for c in courses:
        lines = ["[[ilias.courses]]", f"name = {q(c['name'])}", f"crs = {int(c['crs'])}"]
        if c.get("groups"):
            lines.append(f"groups = {q([int(g) for g in c['groups']])}")
        for k, v in c.items():                         # Preserve other existing settings such as read_pages.
            if k not in ("name", "crs", "groups"):
                lines.append(f"{k} = {q(v)}")
        out.append("\n".join(lines))
    return "\n\n".join(out) + ("\n" if out else "")


def render_config(a: dict, example: dict) -> str:
    """Render wizard answers as config.toml, using config.example.toml defaults for unasked settings."""
    g, llm, ilias = example["general"], example["llm"], example["ilias"]
    accounts = [{"name": "KIT", "host": "imap.kit.edu", "user": a["kit_user"],
                 "password_env": "KIT_PASSWORD"}]
    if a.get("gmail"):
        accounts.append({"name": "Gmail", "host": "imap.gmail.com", "user": a["gmail"],
                         "password_env": "GMAIL_APP_PASSWORD"})
    acc_text = "\n\n".join(
        f"[[accounts]]\nname = {q(x['name'])}\nhost = {q(x['host'])}\nport = 993\n"
        f"user = {q(x['user'])}\npassword_env = {q(x['password_env'])}\nfolder = \"INBOX\"\n"
        f"llm = true                   {tr('cfg.acc_llm')}" for x in accounts)
    head = tr("cfg.head", time=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    return f"""{head}

[general]
language = {q(a['language'])}            {tr('cfg.language')}
since_days = {q(g.get('since_days', 1))}           {tr('cfg.since_days')}
max_per_account = {q(g.get('max_per_account', 100))}
snippet_chars = {q(g.get('snippet_chars', 300))}       {tr('cfg.snippet')}
send_when_empty = {q(g.get('send_when_empty', False))}

[llm]
enabled = true
base_url = {q(a['llm_url'])}
model = {q(a['llm_model'])}
api_key_env = {q(a['llm_key_env'])}
batch_size = {q(llm.get('batch_size', 40))}
about_me = {q(a['about_me'])}
{tr('cfg.ignore')}
always_ignore = [
{"".join(f"  {q(x)},{chr(10)}" for x in tr('cfg.ignore_rules').split(chr(10)))}]

[job]
job_search = false        {tr('cfg.job')}
profile = {q(example.get('job', {}).get('profile', 'Werkstudent'))}

[safety_net]
{tr('cfg.safety')}
always_important_senders = []

[telegram]
bot_token_env = "TELEGRAM_BOT_TOKEN"
chat_id_env = "TELEGRAM_CHAT_ID"

{acc_text}

[ilias]
user = {q(a['kit_user'])}
password_env = "KIT_PASSWORD"
ical_url_env = "ILIAS_ICAL_URL"
quiet_hours = {q(ilias.get('quiet_hours', [0, 7]))}       {tr('cfg.quiet')}
skip_folders = {q(ilias.get('skip_folders', ''))}

{tr('cfg.courses')}
{render_courses(a['courses'])}"""


def render_env(v: dict) -> str:
    """Write empty entries except Gmail so a future .env edit reveals missing values."""
    lines = [tr("env.head")]
    for k in ("KIT_PASSWORD", "GMAIL_APP_PASSWORD", v.get("_llm_key_env", "DEEPSEEK_API_KEY"),
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ILIAS_ICAL_URL"):
        if k in v or k != "GMAIL_APP_PASSWORD":
            lines.append(f"{k}={v.get(k, '')}")
    return "\n".join(lines) + "\n"


def replace_courses(text: str, courses: list[dict]) -> str:
    """Replace every [[ilias.courses]] block while preserving all other config text, including comments."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    block: list[str] | None = None        # Course block currently being skipped.
    insert_at: int | None = None

    def end_block() -> None:
        # Comments and blank lines after a course block belong to the following block, so preserve them.
        keep = []
        while block and (not block[-1].strip() or block[-1].lstrip().startswith("#")):
            keep.insert(0, block.pop())
        out.extend(keep)

    for line in lines:
        s = line.strip()
        if s.startswith("["):
            if block is not None:
                end_block()
                block = None
            if s.replace(" ", "") == "[[ilias.courses]]":
                if insert_at is None:
                    insert_at = len(out)
                block = []
                continue
        if block is not None:
            block.append(line)
        else:
            out.append(line)
    if block is not None:
        end_block()
    new = render_courses(courses)
    if insert_at is None:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append("\n" + new)
    else:
        out.insert(insert_at, new + ("\n" if courses else ""))
    result = "".join(out)
    result = re.sub(r"\n{3,}", "\n\n", result)
    tomllib.loads(result)                  # Fail here for invalid output before saving it.
    return result


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dst = BACKUP_DIR / f"{path.name}.{dt.datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(path, dst)
    return dst


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


# ---------------------------------------------------------------- Course selection

def choose_courses(items: list[dict], existing: dict[int, dict]) -> list[dict]:
    """Turn an ILIAS course list into user-selected courses, preserving settings for existing course IDs."""
    from ilias_courses import groups_by_course, semester_label
    courses = [i for i in items if i["kind"] == "crs"]
    current = [c for c in courses if c.get("current")]
    older = sorted((c for c in courses if not c.get("current")),
                   key=lambda c: c["semester"] or (0, 0), reverse=True)
    shown = list(current)
    if current:
        print(tr("c.current", sem=semester_label(current[0]["semester"])))
    else:
        print(tr("c.none_current"))
    if older and (not current or yes(tr("c.show_older", n=len(older)), default=False)):
        shown += older
    defaults = [i + 1 for i, c in enumerate(shown)
                if (c["ref"] in existing) or (not existing and c.get("current"))]
    for i, c in enumerate(shown, 1):
        if current and i == len(current) + 1:        # Current-semester entries end here; earlier semesters follow.
            print(tr("c.older"))
        mark = "✓" if i in defaults else " "
        sem = "" if c.get("current") else f"  [{semester_label(c['semester'])}]"
        print(f"  {i:2}. {mark} {c['name']}{sem}")
    print(tr("c.pick"))
    print(tr("c.pick_default", list=" ".join(map(str, defaults)) or "-"))
    while True:
        v = input("> ").strip()
        if not v:
            picked = defaults
            break
        if v == "0":
            picked = []
            break
        picked = parse_numbers(v, len(shown))
        if picked is not None:
            break
        print(tr("bad_choice"))
    groups = groups_by_course(items)
    group_titles = {g["ref"]: g["title"] for g in items if g["kind"] == "grp"}
    chosen = []
    for i in picked:
        c = shown[i - 1]
        old = dict(existing.get(c["ref"], {}))
        name = ask(tr("c.name", title=c["title"]), default=old.get("name") or c["name"])
        entry = {**old, "name": name, "crs": c["ref"]}
        g = groups.get(c["ref"]) or old.get("groups") or []
        if g:
            entry["groups"] = g
            print(tr("c.groups", g=tr("c.sep").join(group_titles.get(x, str(x)) for x in g)))
        else:
            entry.pop("groups", None)
        chosen.append(entry)
    # Keep existing courses in order and append new ones, leaving the file unchanged when nothing changed.
    order = list(existing)
    chosen.sort(key=lambda e: order.index(e["crs"]) if e["crs"] in order else len(order))
    print(tr("c.chosen", n=len(chosen)))
    return chosen


def manual_courses(existing: dict[int, dict]) -> list[dict]:
    v = input(tr("c.manual") + " ").strip()
    out = []
    for p in re.split(r"[\s,，、;]+", v):
        if p.isdigit():
            old = dict(existing.get(int(p), {}))
            name = ask(tr("c.manual_name", crs=p), default=old.get("name", ""), required=True)
            out.append({**old, "name": name, "crs": int(p)})
    return out


def fetch_courses(user: str, password: str) -> list[dict]:
    from ilias_courses import my_courses
    from ilias_sync import Ilias
    return my_courses(Ilias(user, password))


# ---------------------------------------------------------------- Flow

def step_kit(a: dict, env: dict, check: bool) -> list[dict] | None:
    """Return the ILIAS course list, or None when validation fails or --no-check is used."""
    title("s.kit")
    while True:
        a["kit_user"] = ask(tr("kit.user"), default=a.get("kit_user", ""), required=True)
        env["KIT_PASSWORD"] = ask_secret(tr("kit.pw"))
        if not check:
            print(tr("skip_check"))
            return None
        print(tr("kit.login"))
        items, ok = None, True
        try:
            items = fetch_courses(a["kit_user"], env["KIT_PASSWORD"])
            print(tr("check_ok", what=tr("kit.ilias_ok")))
        except Exception as e:
            ok = False
            print(tr("check_fail", what=tr("kit.ilias"), err=e))
        try:
            check_imap("imap.kit.edu", a["kit_user"], env["KIT_PASSWORD"])
            print(tr("check_ok", what=tr("kit.imap_ok")))
        except Exception as e:
            ok = False
            print(tr("check_fail", what=tr("kit.imap"), err=e))
        if ok or not yes(tr("retry", file=".env"), default=True):
            return items


def step_courses(items: list[dict] | None, existing: dict[int, dict]) -> list[dict]:
    title("s.courses")
    if items:
        return choose_courses(items, existing)
    return manual_courses(existing)


def step_ical(env: dict) -> None:
    title("s.ical")
    print(tr("ical.help"))
    url = ask(tr("ical.url"))
    if url and not url.startswith("https://"):
        print(tr("ical.bad"))
        url = ""
    if url:
        env["ILIAS_ICAL_URL"] = url


def step_gmail(a: dict, env: dict, check: bool) -> None:
    title("s.gmail")
    if not yes(tr("gmail.want"), default=False):
        return
    print(tr("gmail.help"))
    while True:
        a["gmail"] = ask(tr("gmail.addr"), default=a.get("gmail", ""), required=True)
        env["GMAIL_APP_PASSWORD"] = ask_secret(tr("gmail.pw")).replace(" ", "")
        if not check:
            print(tr("skip_check"))
            return
        try:
            check_imap("imap.gmail.com", a["gmail"], env["GMAIL_APP_PASSWORD"])
            print(tr("check_ok", what=tr("gmail.ok")))
            return
        except Exception as e:
            print(tr("check_fail", what="Gmail", err=e))
            if not yes(tr("retry", file=".env"), default=True):
                return


def step_llm(a: dict, env: dict, example: dict, check: bool) -> None:
    title("s.llm")
    print(tr("llm.help"))
    a["llm_url"] = ask(tr("llm.url"), default=example["llm"].get("base_url", "https://api.deepseek.com"))
    a["llm_model"] = ask(tr("llm.model"), default=example["llm"].get("model", "deepseek-flash"))
    a["llm_key_env"] = "DEEPSEEK_API_KEY" if "deepseek" in a["llm_url"] else "LLM_API_KEY"
    env["_llm_key_env"] = a["llm_key_env"]
    while True:
        env[a["llm_key_env"]] = ask_secret(tr("llm.key"))
        if not check:
            print(tr("skip_check"))
            return
        try:
            check_llm(a["llm_url"], env[a["llm_key_env"]])
            print(tr("check_ok", what=tr("llm.ok")))
            return
        except Exception as e:
            print(tr("check_fail", what=tr("llm.check"), err=e))
            if not yes(tr("retry", file=".env"), default=True):
                return


def step_telegram(env: dict, check: bool) -> None:
    title("s.tg")
    print(tr("tg.help"))
    while True:
        env["TELEGRAM_BOT_TOKEN"] = ask_secret(tr("tg.token"))
        if not check:
            print(tr("skip_check"))
            break
        r = tg_call(env["TELEGRAM_BOT_TOKEN"], "getMe")
        if r.get("ok"):
            name = r["result"].get("username", "?")
            print(tr("check_ok", what=tr("tg.ok", name=name)))
            print(tr("tg.send_now", name=name))
            try:
                cid = wait_for_chat(env["TELEGRAM_BOT_TOKEN"])
            except RuntimeError as e:
                cid = None
                print(tr("tg.busy") if str(e) == "busy" else tr("check_fail", what="Telegram", err=e))
            if cid:
                print(tr("check_ok", what=tr("tg.got", id=cid)))
                env["TELEGRAM_CHAT_ID"] = str(cid)
                return
            print(tr("tg.timeout"))
            break
        print(tr("check_fail", what=tr("tg.check"), err=r.get("description", "?")))
        if not yes(tr("retry", file=".env"), default=True):
            break
    cid = ask(tr("tg.manual"))
    if cid:
        env["TELEGRAM_CHAT_ID"] = cid


def pick_language() -> str:
    """Select the wizard language for following questions and config.toml [general] language."""
    print(i18n.PICK)
    codes = list(i18n.LANGS)
    for i, c in enumerate(codes, 1):
        print(f"  {i}. {i18n.LANGS[c]}")
    while True:
        v = input("> ").strip() or "1"
        if v.isdigit() and 1 <= int(v) <= len(codes):
            lang = codes[int(v) - 1]
            break
    i18n.LANG = lang
    return lang


def run_full(check: bool) -> int:
    example = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    old = tomllib.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    existing = {int(c["crs"]): c for c in old.get("ilias", {}).get("courses", [])}
    a: dict = {"language": pick_language(),
               "kit_user": old.get("ilias", {}).get("user", "")}
    env: dict = {}
    print("\n" + tr("hello"))
    items = step_kit(a, env, check)
    a["courses"] = step_courses(items, existing)
    step_ical(env)
    step_gmail(a, env, check)
    step_llm(a, env, example, check)
    step_telegram(env, check)
    title("s.about")
    print(tr("about.help"))
    a["about_me"] = ask(tr("about.q"), default=tr("about.default"))

    title("s.write")
    text = render_config(a, example)
    tomllib.loads(text)                                      # Generated configuration must be parseable.
    for p in (CONFIG, ENV):
        b = backup(p)
        if b:
            print(tr("w.backup", path=b))
    write_private(CONFIG, text)
    write_private(ENV, render_env(env))
    print(tr("w.done", config=CONFIG, env=ENV))
    if check and env.get("TELEGRAM_CHAT_ID") and yes(tr("w.test_msg"), default=True):
        r = tg_call(env["TELEGRAM_BOT_TOKEN"], "sendMessage",
                    chat_id=env["TELEGRAM_CHAT_ID"], text=tr("w.test_text"))
        print(tr("w.test_ok") if r.get("ok") else tr("check_fail", what="Telegram",
                                                      err=r.get("description")))
    print("\n" + tr("w.next_docker" if Path("/.dockerenv").exists() else "w.next_local"))
    return 0


def run_courses(check: bool) -> int:
    if not CONFIG.exists():
        print(tr("w.no_config"))
        return 1
    from digest import load_env, secret
    text = CONFIG.read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    i18n.use(cfg)
    load_env(ENV)
    icfg = cfg.get("ilias", {})
    existing = {int(c["crs"]): c for c in icfg.get("courses", [])}
    items = None
    if check:
        print(tr("kit.login"))
        try:
            items = fetch_courses(icfg["user"], secret(icfg.get("password_env", "KIT_PASSWORD")))
        except Exception as e:
            print(tr("c.list_fail", err=e))
    courses = step_courses(items, existing)
    new = replace_courses(text, courses)
    b = backup(CONFIG)
    if b:
        print(tr("w.backup", path=b))
    write_private(CONFIG, new)
    print(tr("w.courses_done", n=len(courses)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="安装向导：生成 config.toml 和 .env / "
                                             "Einrichtungsassistent: erstellt config.toml und .env")
    ap.add_argument("--courses", action="store_true",
                    help="新学期：只重新选课程 / neues Semester: nur die Kurse neu wählen")
    ap.add_argument("--no-check", action="store_true",
                    help="不联网检查（测试用）/ ohne Online-Prüfung (für Tests)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    check = not args.no_check
    try:
        if args.courses:
            return run_courses(check)
        if CONFIG.exists():
            try:                                   # Existing settings: ask in their configured language.
                i18n.use(tomllib.loads(CONFIG.read_text(encoding="utf-8")))
            except (OSError, tomllib.TOMLDecodeError):
                pass
            choice = menu(tr("exists", path=CONFIG),
                          [tr("exists.all"), tr("exists.courses"), tr("exists.cancel")])
            if choice == 1:
                return run_courses(check)
            if choice == 2:
                print(tr("cancelled"))
                return 1
        return run_full(check)
    except (KeyboardInterrupt, EOFError):
        print("\n" + tr("cancelled"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
