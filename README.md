# Stabæk Drakt Monitor

Automatisk overvåking av **Finn.no, eBay og Facebook-grupper** for vintage Stabæk-drakter (1993–2003).
Sender varsel rett til mobilen via Telegram når en drakt dukker opp.

---

## Hva du trenger

- **Mac eller PC** med internettilgang
- **Python 3.9 eller nyere** – sjekk med `python3 --version` i Terminal
- **Telegram-appen** på mobilen

> Har du ikke Python? Last ned gratis på https://www.python.org/downloads/
> Husk å krysse av «Add Python to PATH» under installasjonen (Windows).

---

## Steg 1 – Sett opp Telegram-bot

Dette tar ca. 3 minutter.

### 1a. Opprett boten

1. Åpne Telegram og søk etter **@BotFather**
2. Start en chat og skriv: `/newbot`
3. BotFather spør om et navn – f.eks. `Stabæk Drakt Bot`
4. BotFather spør om et brukernavn – f.eks. `stabaekdrakt_bot` (må slutte på «bot»)
5. Du får tilbake en melding som inneholder en lang tekst som starter med `1234567890:ABC...`
   – det er **bot_token** din. Kopier og ta vare på den.

### 1b. Finn din chat-ID

1. Åpne Telegram og søk etter **@userinfobot**
2. Start chat og skriv `/start`
3. Boten svarer med meldingen `Id: 123456789` – det er **chat_id** din.

---

## Steg 2 – Last ned og installer

Åpne **Terminal** (Mac: søk «Terminal» i Spotlight). Naviger til mappen der du la filene:

```bash
cd "/Users/halvorstensholt/Road to grønn arm"
```

Installer Python-avhengigheter (gjøres bare én gang):

```bash
pip3 install -r requirements.txt
```

---

## Steg 3 – Konfigurer appen

Åpne filen **config.yaml** i en teksteditor (f.eks. TextEdit på Mac, Notisblokk på Windows).

Finn disse to linjene og bytt ut placeholders med dine verdier:

```yaml
telegram:
  bot_token: "DIN_BOT_TOKEN_HER"      ← lim inn token fra Steg 1a
  chat_id:   "DIN_CHAT_ID_HER"        ← lim inn ID fra Steg 1b
```

Lagre filen.

---

## Steg 4 – Test at alt fungerer

Kjør en test-runde (søker én gang og avslutter):

```bash
cd "/Users/halvorstensholt/Road to grønn arm"
python3 monitor.py --test
```

Du bør se noe slikt i terminalen:

```
2025-01-15 10:23:01 [INFO   ] monitor: Stabæk Drakt Monitor – test-modus
2025-01-15 10:23:03 [INFO   ] scrapers.finn: Finn.no 'stabæk drakt': 12 treff
...
2025-01-15 10:23:12 [INFO   ] monitor: Test ferdig. Avslutter.
```

**Og på telefonen** skal du få en Telegram-melding:
> 🔍 Test-kjøring startet…
> ✅ Test fullført – ingen nye treff akkurat nå.

Dersom du får en feilmelding, se **Feilsøking** nederst.

---

## Steg 5 – Start overvåkingen

For å starte monitoren (kjør til du stopper den med Ctrl+C):

```bash
cd "/Users/halvorstensholt/Road to grønn arm"
python3 monitor.py
```

Monitoren kjører nå og sjekker hvert 12. minutt. Treff sendes rett til mobilen.

---

## Sette opp Facebook-grupper

Facebook krever at du er logget inn. Appen bruker dine innloggings-cookies til dette.

### Steg A – Eksporter cookies fra nettleseren (gjøres én gang)

1. Åpne Chrome eller Firefox
2. Installer utvidelsen **"Get cookies.txt LOCALLY"**
   - Chrome: søk etter den i Chrome Web Store
   - Firefox: søk etter den i Firefox Add-ons
3. Gå til **facebook.com** og pass på at du er logget inn
4. Klikk på utvidelse-ikonet oppe til høyre
5. Velg **"Export cookies for this tab"** (eller «Current site»)
6. Lagre filen som **`facebook_cookies.txt`** direkte i prosjektmappen
   (`/Users/halvorstensholt/Road to grønn arm/`)

### Steg B – Finn gruppe-ID-ene

1. Gå inn i en Facebook-gruppe du er med i og vil overvåke
2. Se på nettleserlinjen – den viser noe slikt:
   `https://www.facebook.com/groups/kjopsalgdrakter/`
3. Teksten etter `/groups/` (her: `kjopsalgdrakter`) er gruppe-ID-en
4. Åpne **config.yaml** og erstatt plassholderne:

```yaml
facebook:
  enabled: true
  cookies_file: "facebook_cookies.txt"
  groups:
    - "kjopsalgdrakter"        ← bytt med riktig ID
    - "fotballdrakter_norge"   ← bytt med riktig ID
```

**Tips:** Søk i Facebook etter grupper som «kjøp selg fotballdrakter», «norsk fotball drakter», «drakter til salgs» og finn de med flest norske medlemmer.

### Hva skjer når cookies utløper?

Facebook-cookies varer typisk noen uker til måneder. Når appen logger at Facebook-scraping feiler, gjenta Steg A og erstatt `facebook_cookies.txt`.

### Deaktivere Facebook

Vil du midlertidig slå av Facebook (f.eks. hvis cookies er utløpt), sett:
```yaml
facebook:
  enabled: false
```

---

## Autostart når Mac starter

Slik setter du opp at monitoren starter automatisk hver gang du logger inn på Macen.

### Opprett en launchd-fil

Åpne Terminal og kjør:

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/no.stabek.monitor.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>no.stabek.monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/halvorstensholt/Road to grønn arm/monitor.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/halvorstensholt/Road to grønn arm</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/halvorstensholt/Road to grønn arm/monitor.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/halvorstensholt/Road to grønn arm/monitor.log</string>
</dict>
</plist>
EOF
```

### Aktiver den

```bash
launchctl load ~/Library/LaunchAgents/no.stabek.monitor.plist
```

### Sjekk at den kjører

```bash
launchctl list | grep stabek
```

Du skal se `no.stabek.monitor` i listen.

### Stoppe / deaktivere autostart

```bash
launchctl unload ~/Library/LaunchAgents/no.stabek.monitor.plist
```

---

## Slik endrer du søkeordene

Åpne **config.yaml** og finn `finn_keywords`-seksjonen:

```yaml
search:
  finn_keywords:
    - "stabæk drakt"
    - "stabæk fotballdrakt"
    - "stabæk retro"
    # Legg til nye søkeord her, med "-" foran og anførselstegn rundt:
    - "stabæk 1997"
    - "stabæk 1999"
```

Du kan:
- **Legge til** en linje med `    - "nytt søkeord"`
- **Fjerne** en linje ved å slette den
- **Endre intervallet** (minutter) under `interval_minutes`

Restart monitoren etter endringer.

---

## Filtere – hva sendes videre

Et treff sendes til Telegram hvis:
1. "Stabæk" eller "Stabaek" finnes i tittel/beskrivelse
2. Annonsen er **ikke** tydelig en ny 2024/2025-drakt uten retro-merking
3. Det er **ikke** en barnestørrelse (med mindre du endrer `include_children: true`)

Drakter med **grønne ermer, vintage-år (1993–2003), "retro", "Diadora", "Umbro"** etc.
markeres med ⭐ i meldingen.

---

## Eksempel på Telegram-varsel

```
⭐ Stabæk fotballdrakt 1997 Diadora
🟢 GRØNNE ERMER!
💰 450 kr
📍 Finn.no
Treff: grønne ermer | diadora | år 1997
👉 Se annonsen
```

---

## Feilsøking

### "Finner ikke python3"
Installer Python: https://www.python.org/downloads/

### "No module named 'requests'"
Kjør: `pip3 install -r requirements.txt`

### Ingen Telegram-melding i testen
- Dobbeltsjekk `bot_token` og `chat_id` i config.yaml
- Åpne boten i Telegram og trykk **Start** (gjøres bare første gang)
- Test token manuelt i nettleseren:
  `https://api.telegram.org/botDIN_TOKEN/getMe`
  (bytt `DIN_TOKEN` med din token)

### "Finn.no: 0 treff" hele tiden
Finn.no kan ha endret sin HTML-struktur. Sjekk `monitor.log` for feilmeldinger.
Vent noen timer og prøv igjen – det kan skyldes midlertidig blokkering.

### Monitoren krasjer
Åpne `monitor.log` for å se hva som gikk galt:
```bash
tail -50 "/Users/halvorstensholt/Road to grønn arm/monitor.log"
```

---

## Prosjektstruktur

```
Road to grønn arm/
├── monitor.py            – Hoved-skript og scheduler
├── database.py           – Lagrer sette annonser (SQLite)
├── filters.py            – Relevansvurdering
├── notifier.py           – Telegram-varsler
├── scrapers/
│   ├── finn.py           – Finn.no-scraper
│   ├── ebay.py           – eBay UK + DE-scraper
│   └── facebook.py       – Facebook-grupper-scraper
├── config.yaml           – Din konfigurasjon
├── requirements.txt      – Python-avhengigheter
├── facebook_cookies.txt  – Dine Facebook-cookies (du lager denne)
├── seen_ads.db           – Opprettes automatisk
└── monitor.log           – Kjørelogg (opprettes automatisk)
```

---

## Legge til andre klubber senere

Legg til nye søkeord i `config.yaml`:

```yaml
finn_keywords:
  - "vålerenga drakt retro"
  - "brann drakt 90-tall"
```

Filteret sjekker fortsatt at "stabæk" finnes – for å følge andre klubber,
legg dem til i `required_terms` i config.yaml:

```yaml
filters:
  required_terms:
    - "stabæk"
    - "stabaek"
    - "vålerenga"   ← legg til her
```
