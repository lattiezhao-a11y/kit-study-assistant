"""
界面语言：中文 / 德语

  · 设置在 config.toml 的 [general] language = "zh" 或 "de"（不写就是中文）
  · 在 Telegram 里用 /start、/language 点按钮选，或者直接说"我要用德语版"，马上生效
  · 程序里写死、直接发到 Telegram 的文字都在下面的 TEXTS 里，每句都有中文和德语两个版本
  · AI 写的内容（聊天回答、邮件摘要、论坛总结）靠提示词里的「ai.*」那几句决定语言
  · 发给 AI 的提示词、工具结果保持中文（用户看不到，AI 回答时会翻译）

每个脚本读完 config 后调用 use(cfg)；之后 tr("键") 就会给出当前语言的文字。
"""
from __future__ import annotations

import datetime as dt

LANGS = {"zh": "中文", "de": "Deutsch"}
LANG = "zh"                     # 当前语言（use() 设置）

# 选语言时显示的那句话：还不知道用什么语言，所以两种都写
PICK = "请选择语言 / Bitte wähle eine Sprache:"

WEEKDAYS = {"zh": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
            "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]}


def lang_of(cfg: dict) -> str:
    v = str(cfg.get("general", {}).get("language", "zh")).strip().lower()
    return v if v in LANGS else "zh"


def use(cfg: dict) -> str:
    """按 config 设置当前语言，返回语言代码。"""
    global LANG
    LANG = lang_of(cfg)
    return LANG


def tr(key: str, /, **kw) -> str:          # 「/」：文字里也可以有 {key}
    s = TEXTS[key][LANG]
    return s.format(**kw) if kw else s


# ---------------------------------------------------------------- 日期

def weekday(d: dt.date) -> str:
    return WEEKDAYS[LANG][d.weekday()]


def day_label(d: dt.date) -> str:
    """中文 11/30 周一；德语 Mo 30.11."""
    if LANG == "de":
        return f"{weekday(d)} {d.day}.{d.month}."
    return f"{d.month}/{d.day} {weekday(d)}"


def due_label(due: dt.datetime, time_known: bool) -> str:
    """中文 11/30 周一 13:15 / 11/30 周一（没写具体时间）；德语 Mo 30.11. 13:15 / Mo 30.11. (ohne Uhrzeit)"""
    return day_label(due) + (f" {due:%H:%M}" if time_known else tr("no_time"))


def date_text(iso: str, short: bool = False) -> str:
    """YYYY-MM-DD → 显示用。中文保持原样（short：MM-DD）；德语 01.12.2026（short：1.12.）。
    看不懂的（AI 偶尔写错格式）原样返回。"""
    if LANG == "zh":
        return iso[5:] if short else iso
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day}.{d.month}." if short else f"{d.day:02d}.{d.month:02d}.{d.year}"


# ---------------------------------------------------------------- 设置说明（改设置时的预览里显示）
# 中文说明就是 tools.SETTINGS 里的那句，这里只放德语
SETTING_DESC_DE = {
    "always_ignore": "Mails, die immer ignoriert werden (eine Regel pro Zeile)",
    "always_important_senders": "Mails dieser Absender sind mindestens „Zu erledigen“",
    "about_me": "Selbstbeschreibung für die KI, eine Zeile pro Punkt: wer ich bin, was mich interessiert "
                "und was nicht (Mails zu „Kein Interesse: …“ werden ignoriert und nicht erinnert)",
    "job_search": "Suche ich gerade einen Job? (false = Stellenanzeigen werden ignoriert)",
    "quiet_hours": "Von wann bis wann keine dringenden Erinnerungen kommen, z. B. [0, 7]",
    "forum_hour": "Bei welchem Lauf die Forum-Zusammenfassung kommt (1, 7, 13 oder 19 Uhr)",
}


# ---------------------------------------------------------------- 文字

HELP_ZH = """我是你的学习助理 🤖
直接用中文跟我说话就行。

命令：
/language  切换语言（中文 / Deutsch）
/new  清空对话记忆（重新开始）
/usage  看今天和本月花了多少 token
/help  显示这条说明

你可以这样跟我说：
• 作业："还有哪些作业"、"BS 第三次作业交了"、"TGI 作业推迟到周五 12 点"
• 待办："记一下：周三去银行"、"我有哪些待办"
• 邮件（最近 7 天，只读）："今天 KIT 有什么邮件"、"那封 Tutorium 的邮件写了啥"
• 课表："明天有什么课"、"这周的安排"；加课："周一 9:45–11:15 BS 讲座 在 HS a.m. Fasanengarten"
• 论坛："GKI 论坛最近在讨论什么"
• 设置："以后 XX 的邮件都忽略"（我会先给你看改动，你回复「确认」才改）
• 不感兴趣："像 XX 这种我不感兴趣"（记进自我介绍，以后这类邮件不加提醒）"""

HELP_DE = """Ich bin dein Lernassistent 🤖
Schreib mir einfach auf Deutsch.

Befehle:
/language  Sprache wechseln (中文 / Deutsch)
/new  Gesprächsverlauf löschen (neu anfangen)
/usage  Token-Verbrauch heute und in diesem Monat
/help  Diese Hilfe anzeigen

Du kannst mir zum Beispiel schreiben:
• Abgaben: „Welche Abgaben sind noch offen?“, „BS Blatt 3 ist abgegeben“, „TGI-Abgabe auf Freitag 12 Uhr verschieben“
• To-dos: „Merk dir: Mittwoch zur Bank“, „Was steht auf meiner To-do-Liste?“
• Mails (letzte 7 Tage, nur lesen): „Welche KIT-Mails kamen heute?“, „Was steht in der Tutorium-Mail?“
• Stundenplan: „Was habe ich morgen?“, „Was steht diese Woche an?“; Kurs eintragen: „Montag 9:45–11:15 BS Vorlesung im HS a.m. Fasanengarten“
• Forum: „Worüber wird im GKI-Forum gerade diskutiert?“
• Einstellungen: „Mails von XX künftig ignorieren“ (ich zeige dir erst die Änderung, sie gilt erst nach deinem „ja“)
• Kein Interesse: „So etwas wie XX interessiert mich nicht“ (kommt in dein Profil, solche Mails bekommen dann keine Erinnerung mehr)"""

TEXTS: dict[str, dict[str, str]] = {
    # ---- 通用
    "no_time": {"zh": "（没写具体时间）", "de": " (ohne Uhrzeit)"},
    "lang.done": {"zh": "✅ 语言：中文", "de": "✅ Sprache: Deutsch"},
    # 「不感兴趣」这一行的开头：写进 about_me，邮件分类时据此忽略
    "no_interest": {"zh": "不感兴趣：", "de": "Kein Interesse: "},

    # ---- 给 AI 的语言要求（提示词是中文的，只换这几句）
    "ai.reply_rule": {
        "zh": "用中文回答",
        "de": "一律用德语（Deutsch）回答，我用中文说话也用德语答。工具结果大多是中文，转述时翻译成德语；"
              "课程名、ILIAS 作业标题、邮件标题、人名保留原文，以前用中文记下的作业标题、待办内容翻译成德语。"
              "下面规则里的中文例句换成德语说法也一样适用（比如 „alle“ =「全部」，„diese Woche“ =「这周」，"
              "„abgegeben“ =「交了」）",
    },
    "ai.date_example": {"zh": "11/30 周一 13:15", "de": "Mo 30.11. 13:15"},
    "ai.mail_summary": {"zh": "一句中文摘要，不超过40字", "de": "一句德语（Deutsch）摘要，不超过25个词"},
    "ai.forum_summary": {"zh": "用一句中文概括（不超过 40 字）", "de": "用一句德语（Deutsch）概括（不超过 25 个词）"},

    # ---- bot.py
    "bot.help": {"zh": HELP_ZH, "de": HELP_DE},
    "bot.empty": {"zh": "（空回复）", "de": "(leere Antwort)"},
    "bot.today": {"zh": "今天", "de": "Heute"},
    "bot.month": {"zh": "本月", "de": "Dieser Monat"},
    "bot.usage_line": {"zh": "{label}：{tokens:,} token（{calls} 次调用），约 ${cost:.3f}",
                       "de": "{label}: {tokens:,} Token ({calls} Aufrufe), ca. ${cost:.3f}"},
    "bot.usage_note": {"zh": "（只算聊天机器人；邮件、ILIAS 脚本另算）",
                       "de": "(nur der Chatbot; Mail- und ILIAS-Skripte sind nicht mitgezählt)"},
    "bot.too_many_tools": {"zh": "这件事我调用了太多次工具还没弄完，先停下来了。换个说法再试试？",
                           "de": "Dafür habe ich zu viele Werkzeuge gebraucht und abgebrochen. "
                                 "Versuch es bitte anders formuliert."},
    "bot.text_only": {"zh": "目前我只看得懂文字消息。", "de": "Ich verstehe bisher nur Textnachrichten."},
    "bot.new": {"zh": "好，对话记忆清空了，我们重新开始。",
                "de": "Okay, Gesprächsverlauf gelöscht – wir fangen neu an."},
    "bot.not_changed": {"zh": "⚠️ 没改成：{err}（config.toml 没有变）",
                        "de": "⚠️ Nicht geändert: {err} (config.toml ist unverändert)"},
    "bot.pending_cancelled": {"zh": "（刚才那个设置改动已取消，没有修改）",
                              "de": "(Die vorgeschlagene Änderung wurde verworfen, nichts geändert.)"},
    "bot.ai_failed": {"zh": "⚠️ AI 调用失败（HTTP {code}），稍后再试。",
                      "de": "⚠️ KI-Anfrage fehlgeschlagen (HTTP {code}), bitte später nochmal."},
    "bot.error": {"zh": "⚠️ 出错了：{err}", "de": "⚠️ Fehler: {err}"},
    "bot.confirm_hint": {"zh": "回复「确认」生效；回复别的内容就取消（{minutes} 分钟内有效）。",
                         "de": "Antworte mit „ja“, um sie zu übernehmen; jede andere Antwort verwirft sie "
                               "(gültig {minutes} Minuten)."},
    # Telegram 输入框旁边「/」菜单里的命令说明
    "cmd.start": {"zh": "开始 / 选择语言", "de": "Start / Sprache wählen"},
    "cmd.language": {"zh": "切换语言（中文 / Deutsch）", "de": "Sprache wechseln (中文 / Deutsch)"},
    "cmd.new": {"zh": "清空对话记忆", "de": "Gesprächsverlauf löschen"},
    "cmd.usage": {"zh": "今天和本月的 token 用量", "de": "Token-Verbrauch heute / diesen Monat"},
    "cmd.help": {"zh": "使用说明", "de": "Hilfe"},

    # ---- tools.py（改设置：预览和结果由程序直接发出）
    "set.preview": {"zh": "要修改设置「{key}」（{desc}）\n原来：{old}\n改成：{new}",
                    "de": "Einstellung „{key}“ ändern ({desc})\nVorher:{old}\nNachher:{new}"},
    "set.empty": {"zh": " （空）", "de": " (leer)"},
    "set.no_interest_note": {
        "zh": "\n\n以后这类邮件会放进 ⚪ 忽略、不加提醒（摘要底部的「被忽略」列表里还能看到）。",
        "de": "\n\nSolche Mails landen künftig unter ⚪ Ignoriert und bekommen keine Erinnerung "
              "(unten in der Mail-Übersicht weiterhin sichtbar)."},
    "set.done": {"zh": "✅ 设置「{key}」改好了，下次脚本运行时生效。\n改之前的配置备份在 backup/{backup}",
                 "de": "✅ Einstellung „{key}“ geändert, gilt ab dem nächsten Skriptlauf.\n"
                       "Sicherung der alten Konfiguration: backup/{backup}"},
    "set.none_pending": {"zh": "没有等待确认的设置改动。", "de": "Es wartet keine Änderung auf Bestätigung."},
    "set.check_failed": {"zh": "改完检查没通过，没有修改 config.toml",
                         "de": "Prüfung nach der Änderung fehlgeschlagen, config.toml wurde nicht geändert"},

    # ---- digest.py（邮件摘要）
    "cat.must": {"zh": "🔴 必须处理", "de": "🔴 Zu erledigen"},
    "cat.job": {"zh": "💼 求职机会", "de": "💼 Jobangebote"},
    "cat.maybe": {"zh": "🟡 可以看看", "de": "🟡 Lesenswert"},
    "cat.ignore": {"zh": "⚪ 已忽略", "de": "⚪ Ignoriert"},
    "cat.unknown": {"zh": "❔ 未分类", "de": "❔ Nicht eingeordnet"},
    "dg.title": {"zh": "<b>📬 邮件摘要 {date}</b>（共 {n} 封新邮件）",
                 "de": "<b>📬 Mail-Übersicht {date}</b> ({n} neue Mails)"},
    "dg.group": {"zh": "\n<b>{cat}（{n}）</b>", "de": "\n<b>{cat} ({n})</b>"},
    "dg.added": {"zh": "（已加入提醒）", "de": " (zur Erinnerung hinzugefügt)"},
    "dg.dup": {"zh": "（提醒里已有）", "de": " (schon in den Erinnerungen)"},
    "dg.chance": {"zh": " ⏰可选，截止 {date}（没加提醒，想要就跟我说）",
                  "de": " ⏰ optional, Frist {date} (keine Erinnerung – sag Bescheid, wenn du eine willst)"},
    "dg.no_subject": {"zh": "（无标题）", "de": "(kein Betreff)"},
    "dg.ignored_head": {"zh": "\n<b>{cat}（{n}）</b> 邮件都还在邮箱里：",
                        "de": "\n<b>{cat} ({n})</b> – alle Mails sind noch im Postfach:"},
    "dg.ignored_line": {"zh": "· [{acc}] {sender}：{subj}", "de": "· [{acc}] {sender}: {subj}"},
    "dg.more": {"zh": "· ……还有 {n} 封", "de": "· … und {n} weitere"},
    "dg.tokens": {"zh": "\n<i>token 用量：{n:,}</i>", "de": "\n<i>Token-Verbrauch: {n:,}</i>"},
    "dg.read_failed": {"zh": "{acc} 读取失败：{err}", "de": "{acc}: Abruf fehlgeschlagen: {err}"},
    "dg.ai_failed": {"zh": "AI 分类失败：{err}", "de": "KI-Einordnung fehlgeschlagen: {err}"},
    "dg.ddl_failed": {"zh": "截止日期加入提醒失败：{err}",
                      "de": "Fristen konnten nicht in die Erinnerungen übernommen werden: {err}"},
    "dg.user_not_set": {"zh": "config.toml 里这个邮箱的 user 还没改成真实地址",
                        "de": "In config.toml ist für dieses Postfach noch keine echte Adresse (user) eingetragen"},
    "dg.folder": {"zh": "打不开文件夹 {folder}", "de": "Ordner {folder} lässt sich nicht öffnen"},
    "env.missing": {"zh": "缺少环境变量 {name}（写在 .env 里）",
                    "de": "Umgebungsvariable {name} fehlt (gehört in die .env)"},

    # ---- remind.py（早上汇总、3 小时提醒）
    "rm.todo": {"zh": "📝 待办", "de": "📝 To-do"},
    "rm.morning": {"zh": "☀️ <b>近 3 天要做的事</b>", "de": "☀️ <b>Die nächsten 3 Tage</b>"},
    "rm.today": {"zh": "🔴 <b>今天截止</b>", "de": "🔴 <b>Heute fällig</b>"},
    "rm.tomorrow": {"zh": "🟠 <b>明天截止</b>", "de": "🟠 <b>Morgen fällig</b>"},
    "rm.soon": {"zh": "🟡 <b>3 天内</b>", "de": "🟡 <b>In den nächsten 3 Tagen</b>"},
    "rm.urgent": {"zh": "🚨 <b>3 小时内截止</b>", "de": "🚨 <b>In weniger als 3 Stunden fällig</b>"},

    # ---- ilias_sync.py
    "il.passed": {"zh": "已过", "de": "vorbei"},
    "il.hours_left": {"zh": "还剩 {n} 小时", "de": "noch {n} Std."},
    "il.one_day_left": {"zh": "还剩 1 天", "de": "noch 1 Tag"},
    "il.days_left": {"zh": "还剩 {n} 天", "de": "noch {n} Tage"},
    "il.item": {"zh": "• [{course}] <b>{title}</b>\n   ⏰ {due}，{left}",
                "de": "• [{course}] <b>{title}</b>\n   ⏰ {due}, {left}"},
    "il.first": {"zh": "📚 <b>ILIAS 截止时间已开始跟踪</b>（共 {n} 个，请检查有没有漏）",
                 "de": "📚 <b>ILIAS-Fristen werden jetzt verfolgt</b> ({n} insgesamt – bitte prüfen, ob etwas fehlt)"},
    "il.new": {"zh": "📚 <b>ILIAS 新作业 / 截止时间</b>", "de": "📚 <b>Neue ILIAS-Aufgaben / Fristen</b>"},
    "il.footer": {"zh": "<i>截止前 3 天起每天 07:00 提醒，截止前 3 小时再提醒一次（{tokens} token）</i>",
                  "de": "<i>Ab 3 Tagen vor der Frist täglich um 07:00 eine Erinnerung, "
                        "3 Stunden vorher noch einmal ({tokens} Token)</i>"},
    "il.ical_failed": {"zh": "读 ILIAS 日历失败：{err}", "de": "ILIAS-Kalender konnte nicht gelesen werden: {err}"},
    "il.named_err": {"zh": "{name}：{err}", "de": "{name}: {err}"},
    "il.pdf_failed": {"zh": "读 PDF 失败（{where}）：{err}", "de": "PDF konnte nicht gelesen werden ({where}): {err}"},
    "il.forum_failed": {"zh": "论坛总结失败：{err}", "de": "Forum-Zusammenfassung fehlgeschlagen: {err}"},
    "il.ai_failed": {"zh": "AI 提取失败：{err}", "de": "KI-Auswertung fehlgeschlagen: {err}"},
    "il.login_2fa": {"zh": "KIT 登录要求两步验证了，脚本暂时登不进去",
                     "de": "Der KIT-Login verlangt jetzt Zwei-Faktor-Anmeldung, das Skript kommt nicht rein"},
    "il.login_consent": {"zh": "KIT 登录需要先在浏览器里登录一次 ILIAS，确认信息授权页面",
                         "de": "Bitte einmal im Browser bei ILIAS anmelden und die Datenfreigabe bestätigen"},
    "il.login_wrong": {"zh": "ILIAS 登录失败：KIT 用户名或密码不对（.env 里的 KIT_PASSWORD）",
                       "de": "ILIAS-Login fehlgeschlagen: KIT-Benutzername oder Passwort falsch "
                             "(KIT_PASSWORD in der .env)"},
    "il.login_no_saml": {"zh": "ILIAS 登录失败：没收到 KIT 的登录回复，可能登录页面改版了",
                         "de": "ILIAS-Login fehlgeschlagen: keine Antwort vom KIT-Login, "
                               "vielleicht hat sich die Login-Seite geändert"},
    "il.login_not_in": {"zh": "ILIAS 登录后没进到 ILIAS，可能登录流程改版了",
                        "de": "Nach dem Login nicht in ILIAS gelandet, vielleicht hat sich der Ablauf geändert"},
    "il.too_many_pages": {"zh": "一次打开超过 {n} 个页面，已停止（检查 config 里的课程设置）",
                          "de": "Mehr als {n} Seiten auf einmal geöffnet, abgebrochen "
                                "(Kurseinstellungen in der config prüfen)"},

    # ---- forums.py（论坛每日总结）
    "fo.title": {"zh": "💬 <b>ILIAS 论坛今日新帖</b>（{n} 个讨论串）",
                 "de": "💬 <b>Neue Beiträge im ILIAS-Forum heute</b> ({n} Threads)"},
    "fo.thread": {"zh": "• {title}（{n} 个新帖{tag}）", "de": "• {title} ({n} neue Beiträge{tag})"},
    "fo.teacher": {"zh": "，有老师回复", "de": ", mit Antwort von Lehrenden"},
    "fo.tokens": {"zh": "\n<i>论坛总结用了 {n} token</i>", "de": "\n<i>Forum-Zusammenfassung: {n} Token</i>"},
    "fo.forum_err": {"zh": "论坛 {course}：{err}", "de": "Forum {course}: {err}"},
    "fo.thread_err": {"zh": "讨论串「{title}」：{err}", "de": "Thread „{title}“: {err}"},
    "fo.too_many": {"zh": "有新帖的讨论串有 {n} 个，只总结了 {max} 个",
                    "de": "{n} Threads mit neuen Beiträgen, nur {max} davon zusammengefasst"},
}
