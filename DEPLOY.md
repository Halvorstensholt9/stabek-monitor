# Flytt boten til ekte 24/7-drift

GitHub struper hyppige kjøringer. For at boten skal sjekke kontinuerlig
(døgnet rundt, uten pauser) bør den kjøre på en alltid-på vert. Alt er
ferdig forberedt – du trenger bare opprette **én konto**, så gjør resten seg
nesten selv (boten bygges automatisk fra denne mappa via `Dockerfile`).

Du må sette tre **miljøvariabler** (hemmeligheter) på verten. Verdiene står i
din lokale `config.yaml` på Mac-en:

| Variabel | Hvor finner du verdien |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `config.yaml` → `telegram: bot_token` |
| `TELEGRAM_CHAT_ID`   | `config.yaml` → `telegram: chat_id` |
| `ANTHROPIC_API_KEY`  | din Claude-API-nøkkel (for bildegjenkjenning) |

---

## Alternativ A – Railway (enklest, ~50 kr/mnd)

Helt nettleser-basert, ingen kommandolinje.

1. Gå til **https://railway.app** og logg inn med **GitHub**.
2. **New Project → Deploy from GitHub repo** → velg `stabek-monitor`.
3. Railway oppdager `Dockerfile` og bygger boten automatisk.
4. Åpne tjenesten → **Variables** → legg inn de tre variablene over.
5. Ferdig. Boten kjører nå kontinuerlig. Se «Deployments → Logs» for status.

> Railway gir litt gratis prøvekreditt; deretter ~5 USD/mnd for å stå på 24/7.

---

## Alternativ B – Oracle Cloud (gratis for alltid, litt mer oppsett)

Gratis ARM-maskin som aldri stopper. Jeg guider deg gjennom hele oppsettet
når kontoen er klar.

1. Gå til **https://www.oracle.com/cloud/free/** → **Start for free**.
2. Opprett konto (krever kort for verifisering, men du belastes **ikke** for
   «Always Free»-maskinen).
3. Gi meg beskjed når kontoen er klar – så setter jeg opp maskinen, laster
   opp boten, og starter den (jeg gir deg de eksakte kommandoene/klikkene).

---

## Alternativ C – Fly.io (gratis-allowance, krever litt kommandolinje)

1. **https://fly.io** → opprett konto.
2. Si fra – jeg lager `fly.toml` og gir deg de få kommandoene som skal til.

---

### Hva skjer med GitHub-versjonen?

Den fortsetter å kjøre som backup (nær-kontinuerlig 5-timers løkke). Når
vert-løsningen er oppe og går, kan vi skru av GitHub-kjøringen så du slipper
dobbel-varsler – si fra, så ordner jeg det.
