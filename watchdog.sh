#!/bin/bash
# Watchdog for Stabæk-monitor.
#
# Bakgrunn: når launchd kjører monitor.py DIREKTE, henger Python i
# uninterruptible kernel-wait (STAT=U) under import – en kjent macOS
# launchd/objc-fork-kontekst-bug. Når monitoren startes nohup-detached
# fra et shell-miljø, kjører den feilfritt.
#
# Denne watchdogen kjøres av launchd hvert 3. minutt. Den er triviell
# (ingen tunge imports), så den rammes ikke av U-hengen. Den sjekker om
# monitor.py kjører fra prosjektmappen, og starter den nohup-detached
# hvis ikke.

DIR="/Users/halvorstensholt/Road to grønn arm"
cd "$DIR" || exit 1

# Tell monitor.py-prosesser som kjører FRA prosjektmappen
running=0
for p in $(pgrep -f "monitor.py"); do
    cwd=$(lsof -a -p "$p" -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-)
    case "$cwd" in
        *"Road to gr"*) running=1 ;;
    esac
done

if [ "$running" -eq 1 ]; then
    exit 0   # monitor lever – ingenting å gjøre
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitor nede – starter nohup-detached" >> "$DIR/watchdog.log"
# Fang krasj-output (siste oppstart) i egen fil – så vi ser HVORFOR den
# evt. dør i stedet for å miste bevisene til /dev/null.
nohup bash "$DIR/start_monitor.sh" > "$DIR/monitor_crash.log" 2>&1 &
disown 2>/dev/null || true
