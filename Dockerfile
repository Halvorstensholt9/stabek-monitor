# Stabæk-monitor – kjører kontinuerlig på en hvilken som helst vert
# (Railway, Fly.io, Oracle Cloud, VPS ...). Bygger selv; ingen manuelle steg.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Avhengigheter først (bedre lag-caching)
COPY requirements.txt .
RUN pip install -r requirements.txt
# Headless Chromium for Tise (Playwright) + system-avhengigheter
RUN playwright install --with-deps chromium

# Resten av koden
COPY . .
# config.yaml lages fra malen; ekte hemmeligheter settes som MILJØVARIABLER
# på verten (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY).
RUN cp config.template.yaml config.yaml

# Kjør boten i ÉN sammenhengende løkke (ekte 24/7 – ingen cron-struping).
# 525600 min = 1 år; verten restarter prosessen automatisk om den stopper.
CMD ["python", "monitor.py", "--loop-minutes", "525600"]
