#!/usr/bin/env bash
# Stabæk-monitor – ett-kommandos oppsett på en Oracle Cloud Ubuntu-maskin.
# Installerer Docker, bygger boten og starter den slik at den kjører 24/7
# og overlever omstart. Kjør slik (på serveren):
#
#   curl -fsSL https://raw.githubusercontent.com/Halvorstensholt9/stabek-monitor/main/deploy/oracle-setup.sh -o setup.sh
#   bash setup.sh
#
set -euo pipefail

echo "════════════════════════════════════════════"
echo "  Stabæk-monitor – oppsett på Oracle Cloud"
echo "════════════════════════════════════════════"

if ! command -v apt-get >/dev/null 2>&1; then
  echo "❌ Dette scriptet er laget for UBUNTU. Lag maskinen på nytt med"
  echo "   'Canonical Ubuntu' som image, og kjør scriptet igjen."
  exit 1
fi

echo "→ Installerer Docker + git ..."
sudo apt-get update -y
sudo apt-get install -y docker.io git
sudo systemctl enable --now docker

echo "→ Henter siste versjon av boten ..."
cd ~
if [ -d stabek-monitor ]; then
  cd stabek-monitor && git pull
else
  git clone https://github.com/Halvorstensholt9/stabek-monitor.git
  cd stabek-monitor
fi

echo "→ Bygger boten (laster ned Chromium – kan ta noen minutter) ..."
sudo docker build -t stabek-monitor .

echo ""
echo "Lim inn de tre hemmelighetene (fra config.yaml på Mac-en din):"
read -rp "  TELEGRAM_BOT_TOKEN: " TG_TOKEN
read -rp "  TELEGRAM_CHAT_ID:   " TG_CHAT
read -rp "  ANTHROPIC_API_KEY:  " ANTH

echo "→ Starter boten (kjører 24/7, restarter automatisk) ..."
sudo docker rm -f stabek 2>/dev/null || true
sudo docker run -d --name stabek --restart always \
  -e TELEGRAM_BOT_TOKEN="$TG_TOKEN" \
  -e TELEGRAM_CHAT_ID="$TG_CHAT" \
  -e ANTHROPIC_API_KEY="$ANTH" \
  stabek-monitor

echo ""
echo "✅ Ferdig! Boten kjører nå kontinuerlig."
echo "   Se live logg:   sudo docker logs -f stabek"
echo "   Stoppe:         sudo docker stop stabek"
echo "   Starte igjen:   sudo docker start stabek"
