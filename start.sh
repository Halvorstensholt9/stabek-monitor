#!/bin/bash
# Railway startup-script
# Alltid kopier config.template.yaml → config.yaml
# (credentials overstyres av TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID miljøvariabler)
echo "Kopierer config.template.yaml → config.yaml"
cp config.template.yaml config.yaml
exec python monitor.py
