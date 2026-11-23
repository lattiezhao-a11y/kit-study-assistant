# Mit Docker auf einem Cloud-Server einrichten

[English](deploy-cloud.md) · [中文](deploy-cloud.zh-CN.md) · **Deutsch**

Kein Raspberry Pi? Jeder kleine Linux-Server, der immer läuft, tut es genauso. Diese Anleitung dauert etwa 30 Minuten,
vom leeren Server bis zur ersten Nachricht in Telegram.

## 1. Einen Server besorgen

| Möglichkeit | Kosten | Hinweise |
|---|---|---|
| [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/) | kostenlos | „Always Free“-VMs. Für die Anmeldung braucht man eine Kreditkarte, und die kostenlosen Arm-Maschinen sind manchmal „out of capacity“. Später nochmal versuchen oder die kleine kostenlose AMD-VM nehmen |
| [Hetzner Cloud](https://www.hetzner.com/cloud) | ca. 4–5 €/Monat | Server in Deutschland, schnell eingerichtet. Aktuelle Preise auf der Website |
| Eigenes NAS, Heimserver, alter Laptop | kostenlos | Alles, worauf Docker läuft und das eingeschaltet bleibt |

Nimm **Ubuntu 24.04** (oder Debian) in der kleinsten Größe (1 GB RAM reicht) und melde dich mit einem **SSH-Schlüssel** an.

> **Dein KIT-Passwort liegt dann auf diesem Server.** Nur mit SSH-Schlüssel anmelden, das System aktuell halten und nichts
> installieren, dem du nicht vertraust. Nur du solltest Zugriff haben.

Wenn der Server nur ein `root`-Konto hat (bei Hetzner ist das so), leg zuerst einen normalen Benutzer an:

```bash
adduser student && usermod -aG sudo student
rsync -a ~/.ssh /home/student/ && chown -R student: /home/student/.ssh
# abmelden und neu anmelden: ssh student@<server-ip>
```

Nicht nötig, aber empfohlen: eine Firewall, die nur SSH durchlässt.

```bash
sudo apt update && sudo apt install -y ufw
sudo ufw allow OpenSSH && sudo ufw enable
```

Der Bot braucht keinen offenen Port, weil er seine Nachrichten selbst bei Telegram abholt.

## 2. Docker installieren

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# ab- und wieder anmelden, dann prüfen:
docker compose version
```

## 3. Code holen und den Einrichtungsassistenten starten

Halte bereit: dein KIT-Konto mit Passwort, einen API-Key für eine KI ([DeepSeek](https://platform.deepseek.com/api_keys) ist günstig)
und einen Telegram-Bot-Token (in Telegram [@BotFather](https://t.me/BotFather) anschreiben und `/newbot` schicken).

```bash
git clone https://github.com/lattiezhao-a11y/kit-study-assistant.git
cd kit-study-assistant
mkdir data
docker compose build
docker compose run --rm assistant python3 wizard.py
```

Der Assistent fragt zuerst nach der Sprache (Chinesisch oder Deutsch). Dann meldet er sich bei ILIAS an und listet deine Kurse auf,
die aus diesem Semester sind schon ausgewählt. Jedes Passwort wird sofort geprüft, und sobald du deinem Bot eine Nachricht schickst,
findet er deine Telegram-Chat-ID selbst. Das dauert etwa 5 Minuten; gespeichert wird erst nach der letzten Frage.
(Lieber von Hand? `mail_digest/config.example.toml` nach `data/config.toml` und `mail_digest/.env.example` nach `data/.env` kopieren.)

Alles, was dir gehört, liegt in `data/`: deine Einstellungen, deine Passwörter und die Dateien, die das Programm anlegt (`deadlines.json` …).
Der Code-Ordner wird nie verändert, deshalb sind Updates unproblematisch.

## 4. Erst testen (es wird nichts gesendet)

```bash
docker compose run --rm assistant python3 digest.py --dry-run --no-llm   # kann es deine Mails lesen?
docker compose run --rm assistant python3 digest.py --dry-run            # mit KI-Einordnung
docker compose run --rm assistant python3 ilias_sync.py --dry-run        # ILIAS-Fristen
```

`--dry-run` gibt nur aus. Es wird nichts an Telegram geschickt und nichts gespeichert.

## 5. Starten

```bash
docker compose up -d
docker compose logs -f      # zusehen, was passiert (Strg+C beendet nur das Zusehen, das Programm läuft weiter)
```

Fertig. Nach einem Neustart des Servers startet der Container von selbst wieder. Schick deinem Bot in Telegram eine Nachricht zum Ausprobieren.
Der Zeitplan ist derselbe wie bei der Raspberry-Pi-Version (deutsche Zeit):

| Was | Wann |
|---|---|
| Mails + ILIAS prüfen | 01:30, 07:30, 13:30, 19:30 (ein verpasster Lauf wird nach einem Neustart nachgeholt) |
| Morgenübersicht | 07:00 |
| Dringende Erinnerung (< 3 Std.) | stündlich 07:05–23:05 |
| Chat-Bot | immer |

Nur Erinnerungen, ohne Chat-Bot? In `docker-compose.yml` das `#` vor der Zeile `command:` entfernen.

## Befehle für den Alltag

```bash
docker compose logs -f --tail 100                     # die letzten Log-Zeilen
docker compose restart                                # nach Änderungen an data/config.toml oder data/.env
docker compose run --rm assistant python3 wizard.py --courses && docker compose restart   # neues Semester: Kurse neu wählen
git pull && docker compose up -d --build              # auf die neueste Version aktualisieren
docker compose run --rm assistant python3 tests/run_tests.py --no-llm   # Selbsttest, 0 Token
docker compose down                                   # stoppen
```

**Neues Semester:** Tritt zuerst in ILIAS den Kursen dieses Semesters bei, dann schick dem Bot in Telegram `/courses` und kreuze sie an (der Bot sieht nur Kurse, denen du in ILIAS beigetreten bist). Kein Neustart nötig. Die Zeile `wizard.py --courses` oben macht dasselbe im Terminal.

Zum Sichern reicht der Ordner `data/`.

## Häufige Probleme

- **`Permission denied` bei Dateien in `data/`:** Der Container läuft als Benutzer-ID 1000. Hat dein Benutzer eine andere ID
  (prüfen mit `id -u`), starte mit `PUID=$(id -u) PGID=$(id -g) docker compose up -d` oder trag beide Werte in eine `.env`-Datei neben `docker-compose.yml` ein.
- **Der Bot antwortet doppelt oder gar nicht:** Pro Telegram-Token darf nur ein Bot laufen.
  Prüf, ob er nicht noch woanders läuft, z. B. auf einem Raspberry Pi.
- **ILIAS-Login klappt nicht:** `docker compose run --rm assistant python3 ilias_sync.py --dry-run` ausführen und die Fehlermeldung lesen.
  Verlangt das KIT eine Zwei-Faktor-Anmeldung, kommt das Skript vorerst nicht rein.
