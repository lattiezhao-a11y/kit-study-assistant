# KIT Study Assistant：代码在 /app，数据（config.toml、.env、*.json）在 /data
FROM python:3.13-slim

# pdftotext 读作业 PDF；tzdata 让时间按德国时区算
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Berlin \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY mail_digest/ /app/

# 检查一遍：Python 文件都能编译，调度表能读出来
RUN python3 -m py_compile /app/*.py && DATA_DIR=/tmp python3 /app/scheduler.py --list

VOLUME /data
CMD ["python3", "scheduler.py"]
