FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VAULT_ROOT=/vault \
    STATE_ROOT=/state

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin jarvis

COPY app/ /app/

USER 10001:10001

ENTRYPOINT ["python", "/app/server.py"]
