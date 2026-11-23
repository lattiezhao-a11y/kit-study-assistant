# KIT Study Assistant: code in /app, data (config.toml, .env, *.json) in /data
FROM python:3.13-slim

# pdftotext reads exercise PDFs; tzdata keeps times in the German time zone
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Berlin \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY mail_digest/ /app/

# Sanity check: every Python file compiles and the timetable can be read
RUN python3 -m py_compile /app/*.py && DATA_DIR=/tmp python3 /app/scheduler.py --list

VOLUME /data
CMD ["python3", "scheduler.py"]
