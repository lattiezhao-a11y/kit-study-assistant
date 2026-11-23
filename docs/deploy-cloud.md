# Deploy on a cloud server with Docker

**English** · [中文](deploy-cloud.zh-CN.md)

No Raspberry Pi? Any small Linux server that is always on works just as well. This guide takes about 30 minutes,
from an empty server to the first message in Telegram.

## 1. Get a server

| Option | Cost | Notes |
|---|---|---|
| [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) | free | "Always Free" VMs. A credit card is needed for sign-up, and the free Arm machines are sometimes "out of capacity". Just retry later, or use the small free AMD VM |
| [Hetzner Cloud](https://www.hetzner.com/cloud) | about €4–5/month | Servers in Germany, quick setup. Check the website for current prices |
| Your own NAS / home server / old laptop | free | Anything that runs Docker and stays on |

Pick **Ubuntu 24.04** (or Debian), the smallest size is enough (1 GB RAM is plenty), and log in with an **SSH key**.

> **Your KIT password will live on this server.** Use SSH keys only, keep the system updated, and don't install anything else
> you don't trust. Only you should have access.

If the server only gives you `root` (Hetzner does), create a normal user first:

```bash
adduser student && usermod -aG sudo student
rsync -a ~/.ssh /home/student/ && chown -R student: /home/student/.ssh
# log out, then log in again as: ssh student@<server-ip>
```

Optional but recommended: a firewall that only lets SSH in.

```bash
sudo apt update && sudo apt install -y ufw
sudo ufw allow OpenSSH && sudo ufw enable
```

The bot doesn't need any open port, because it fetches messages from Telegram itself.

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out and in again, then check:
docker compose version
```

## 3. Get the code and run the setup wizard

Have these ready: your KIT account and password, an LLM API key ([DeepSeek](https://platform.deepseek.com/api_keys) is cheap),
and a Telegram bot token (in Telegram, message [@BotFather](https://t.me/BotFather) and send `/newbot`).

```bash
git clone https://github.com/lattiezhao-a11y/kit-study-assistant.git
cd kit-study-assistant
mkdir data
docker compose build
docker compose run --rm assistant python3 setup.py
```

The wizard logs in to ILIAS and lists your courses, with this semester's already selected. It checks every password right away,
and finds your Telegram chat ID once you send your bot a message. It takes about 5 minutes. Nothing is saved before the last question.
(Prefer editing by hand? Copy `mail_digest/config.example.toml` to `data/config.toml` and `mail_digest/.env.example` to `data/.env`.)

Everything that is yours lives in `data/`: your settings, your passwords and the files the program creates (`deadlines.json` …).
The code folder never changes, so updating is safe.

## 4. Test first (nothing is sent)

```bash
docker compose run --rm assistant python3 digest.py --dry-run --no-llm   # can it read your mail?
docker compose run --rm assistant python3 digest.py --dry-run            # with AI classification
docker compose run --rm assistant python3 ilias_sync.py --dry-run        # ILIAS deadlines
```

`--dry-run` only prints. It doesn't send to Telegram and doesn't save anything.

## 5. Start

```bash
docker compose up -d
docker compose logs -f      # watch what it does (Ctrl+C to stop watching)
```

That's it. The container starts again by itself after a reboot. Send your bot a message in Telegram to try it.
It runs on the same schedule as the Raspberry Pi version (German time):

| What | When |
|---|---|
| Email + ILIAS check | 01:30, 07:30, 13:30, 19:30 (a missed run is caught up after a restart) |
| Morning summary | 07:00 |
| Urgent reminder (< 3 h left) | every hour 07:05–23:05 |
| Chat bot | always |

Only want the reminders, without the chat bot? Uncomment the `command:` line in `docker-compose.yml`.

## Everyday commands

```bash
docker compose logs -f --tail 100                     # recent log
docker compose restart                                # after editing data/config.toml or data/.env
docker compose run --rm assistant python3 setup.py --courses && docker compose restart   # new semester: pick courses again
git pull && docker compose up -d --build              # update to the newest version
docker compose run --rm assistant python3 tests/run_tests.py --no-llm   # self-test, 0 tokens
docker compose down                                   # stop
```

Back up the `data/` folder and you have backed up everything.

## Troubleshooting

- **`Permission denied` for files in `data/`:** the container runs as user ID 1000. If your user has another ID
  (check with `id -u`), start with `PUID=$(id -u) PGID=$(id -g) docker compose up -d`, or put both values in a `.env` file next to `docker-compose.yml`.
- **The bot answers twice, or doesn't answer at all:** only one copy of the bot may run per Telegram token.
  Make sure it's not also running somewhere else, such as on a Raspberry Pi.
- **ILIAS login fails:** run `docker compose run --rm assistant python3 ilias_sync.py --dry-run` and read the error message.
  If KIT asks for two-factor authentication, the script can't log in yet.
