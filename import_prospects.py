"""
Spara Energia – CRM-tietojen tuonti Google Sheets -datasta Supabaseen
Ajettava: python3 import_prospects.py
"""
import json, re, requests, sys

SUPABASE_URL  = "https://ggkuodyaddngzskpgvlt.supabase.co"
SUPABASE_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imdna3"
                 "VvZHlhZGRuZ3pza3Bndmx0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI4OTAzMTksImV4cCI6Mj"
                 "A5ODQ2NjMxOX0.Zq_33WUts-Io07HLeHuktACTxKenyuRY--ZHOXZoVlw")

HEADERS = {
    "apikey": SUPABASE_ANON,
    "Authorization": f"Bearer {SUPABASE_ANON}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

# ── Parseri ────────────────────────────────────────────────────────────────────
def parse_row(line):
    """Muunna markdown-piperivit listaksi."""
    cols = [c.strip() for c in line.split("|")]
    # Ensimmäinen ja viimeinen on tyhjä (| alussa/lopussa)
    if cols and cols[0] == "": cols = cols[1:]
    if cols and cols[-1] == "": cols = cols[:-1]
    return cols

def clean(v):
    """Siivoa markdown-erikoismerkit ja tyhjät."""
    if not v or v.strip() in ("", "–", "-", "—"):
        return None
    v = v.strip()
    v = re.sub(r"\\+", "", v)           # poista backslash
    v = re.sub(r"\[merged\].*", "", v).strip()
    if not v or v in ("–", "-", "—"):
        return None
    return v

def clean_num(v):
    """Ota ensimmäinen numero merkkijonosta."""
    if not v: return None
    m = re.search(r"[\d]+[\.,]?[\d]*", v.replace(" ", "").replace("\xa0",""))
    if m:
        try: return float(m.group().replace(",","."))
        except: pass
    return None

def detect_vaihe(kontaktoinnin_tila, tulos):
    """Johda CRM-vaihe Sheets-statuksesta."""
    combined = f"{kontaktoinnin_tila or ''} {tulos or ''}".lower()
    if "sopimus" in combined or "kauppa" in combined:
        return "Sopimus"
    if "tarjous" in combined:
        return "Tarjous"
    if "tapaaminen" in combined or "sovittu" in combined:
        return "Tapaaminen"
    if "reititys vahvistettu" in combined or "nimetty" in combined or "vahvistettu" in combined:
        return "Yhteytetty"
    return "Uusi"

# ── Lue tiedosto ──────────────────────────────────────────────────────────────
CACHE = "/root/.claude/projects/-home-user-Talorekkari/ecb90eb0-e6c8-5c5d-bb53-9ebba74bbec8/tool-results/mcp-Google_Drive-read_file_content-1784744480931.txt"
with open(CACHE) as f:
    raw = json.load(f)
lines = raw["fileContent"].split("\n")

# ─────────────────────────────────────────────────────────────────────────────
# LOHKO 1: ETJ+ (rivit 4–93, 27 saraketta)
# Sarakkeet: ID|Kampanja|Prioriteetti|Segmentti|Tili|Juridinen|Osoite|Kaupunki|
#            Y-tunnus|Liikevaihto|Kulutus MWh|Pisteet|Vaihde|YleinenMail|WWW|
#            Signaali|Perustelu|Rajaus|Huomiot|KontaktointiTila|Tulos|Lahde|
#            Yhteyshenkilö|Titteli|SuoraNro|HenkSahkoposti|LinkedIn
# ─────────────────────────────────────────────────────────────────────────────
etj_rows = []
for line in lines[3:93]:          # 0-indexed: rivit 4–93
    if not line.startswith("|"): continue
    c = parse_row(line)
    if len(c) < 5: continue
    spara_id = clean(c[0])
    if not spara_id or not spara_id.startswith("ID"): continue

    kontaktoinnin_tila = clean(c[19]) if len(c) > 19 else None
    tulos              = clean(c[20]) if len(c) > 20 else None

    row = {
        "spara_id":           spara_id,
        "kampanja":           clean(c[1]),
        "prioriteetti":       clean(c[2]),
        "segmentti":          clean(c[3]),
        "yritys_nimi":        clean(c[4]) or "–",
        "juridinen_yhtio":    clean(c[5]),
        "osoite":             clean(c[6]),
        "kaupunki":           clean(c[7]),
        "y_tunnus":           clean(c[8]),
        "liikevaihto_meur":   clean(c[9]),
        "kulutusarvio_mwh":   clean(c[10]),
        "pisteet":            clean_num(c[11]) if len(c) > 11 else None,
        "vaihde_puhelin":     clean(c[12]) if len(c) > 12 else None,
        "yleinen_sahkoposti": clean(c[13]) if len(c) > 13 else None,
        "www":                clean(c[14]) if len(c) > 14 else None,
        "signaali":           clean(c[15]) if len(c) > 15 else None,
        "perustelu":          clean(c[16]) if len(c) > 16 else None,
        "velvoiteluokka":     clean(c[17]) if len(c) > 17 else None,
        "huomiot":            clean(c[18]) if len(c) > 18 else None,
        "kontaktoinnin_tila": kontaktoinnin_tila,
        "tulos_seuraava_toimi": tulos,
        "lahde":              clean(c[21]) if len(c) > 21 else None,
        "yhteyshenkilö":      clean(c[22]) if len(c) > 22 else None,
        "titteli":            clean(c[23]) if len(c) > 23 else None,
        "suora_numero":       clean(c[24]) if len(c) > 24 else None,
        "henk_sahkoposti":    clean(c[25]) if len(c) > 25 else None,
        "linkedin":           clean(c[26]) if len(c) > 26 else None,
        "vaihe":              detect_vaihe(kontaktoinnin_tila, tulos),
    }
    etj_rows.append(row)

print(f"ETJ+ rivejä: {len(etj_rows)}")

# ─────────────────────────────────────────────────────────────────────────────
# LOHKO 2: Talopakettivalmistajat FIN (rivit 98–147)
# Sarakkeet: Sija|Yritys|Brändi/konserni|Tyyppi|LV|Tähti|Yhteyshenkilö|
#            Titteli|Puhelin|Sähköposti|Spostu|LinkedIn|Signaali|Lahde|
#            MuitaKontakteja|Muistiinpanot|Huomiot
# ─────────────────────────────────────────────────────────────────────────────
talo_rows = []
for i, line in enumerate(lines[97:147]):
    if not line.startswith("|"): continue
    c = parse_row(line)
    if len(c) < 4: continue
    sija_raw = clean(c[0])
    if not sija_raw or not sija_raw.isdigit(): continue

    # Generoi spara_id
    spara_id = f"TALOFIN{int(sija_raw):03d}"
    yritys   = clean(c[1])
    if not yritys: continue

    kontaktoinnin_tila = clean(c[15]) if len(c) > 15 else None
    huomiot            = clean(c[16]) if len(c) > 16 else None

    row = {
        "spara_id":           spara_id,
        "kampanja":           "Talopakettivalmistajat FIN",
        "prioriteetti":       sija_raw,
        "sija":               int(sija_raw),
        "segmentti":          clean(c[3]),           # Tyyppi
        "yritys_nimi":        yritys,
        "juridinen_yhtio":    clean(c[2]),           # Brändi/konserni
        "liikevaihto_meur":   clean(c[4]),
        "pisteet":            clean_num(c[5]) if len(c) > 5 else None,
        "yhteyshenkilö":      clean(c[6]) if len(c) > 6 else None,
        "titteli":            clean(c[7]) if len(c) > 7 else None,
        "vaihde_puhelin":     clean(c[8]) if len(c) > 8 else None,
        "yleinen_sahkoposti": clean(c[9]) if len(c) > 9 else None,
        "linkedin":           clean(c[11]) if len(c) > 11 else None,
        "signaali":           clean(c[12]) if len(c) > 12 else None,
        "lahde":              clean(c[13]) if len(c) > 13 else None,
        "huomiot":            huomiot,
        "kontaktoinnin_tila": kontaktoinnin_tila,
        "vaihe":              detect_vaihe(kontaktoinnin_tila, None),
    }
    talo_rows.append(row)

print(f"Talopakettivalmistajat FIN rivejä: {len(talo_rows)}")

# ─────────────────────────────────────────────────────────────────────────────
# LOHKO 3: Talopakettivalmistajat SWE (rivit 236–255)
# Sarakkeet: Sija|Yritys|Konserni/omistaja|Typ|Omsättning|Poäng|VD/kontakt|
#            Titel|Telefon|E-post|E-postformat|LinkedIn|Signal|…
# ─────────────────────────────────────────────────────────────────────────────
swe_rows = []
for i, line in enumerate(lines[235:]):
    if not line.startswith("|"): continue
    c = parse_row(line)
    if len(c) < 4: continue
    sija_raw = clean(c[0])
    if not sija_raw or not sija_raw.isdigit(): continue

    spara_id = f"TALOSWE{int(sija_raw):03d}"
    yritys   = clean(c[1])
    if not yritys: continue

    row = {
        "spara_id":           spara_id,
        "kampanja":           "Talopakettivalmistajat SWE",
        "prioriteetti":       sija_raw,
        "sija":               int(sija_raw),
        "segmentti":          clean(c[3]),
        "yritys_nimi":        yritys,
        "juridinen_yhtio":    clean(c[2]),
        "liikevaihto_meur":   clean(c[4]),
        "pisteet":            clean_num(c[5]) if len(c) > 5 else None,
        "yhteyshenkilö":      clean(c[6]) if len(c) > 6 else None,
        "titteli":            clean(c[7]) if len(c) > 7 else None,
        "vaihde_puhelin":     clean(c[8]) if len(c) > 8 else None,
        "yleinen_sahkoposti": clean(c[9]) if len(c) > 9 else None,
        "linkedin":           clean(c[11]) if len(c) > 11 else None,
        "signaali":           clean(c[12]) if len(c) > 12 else None,
        "vaihe":              "Uusi",
    }
    swe_rows.append(row)

print(f"Talopakettivalmistajat SWE rivejä: {len(swe_rows)}")

# ── Yhdistä ja tuo ────────────────────────────────────────────────────────────
all_rows = etj_rows + talo_rows + swe_rows
print(f"\nYhteensä: {len(all_rows)} prospektia")

def upsert_batch(rows):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/crm_prospects",
        headers=HEADERS,
        json=rows,
    )
    if r.status_code not in (200, 201):
        print(f"  VIRHE {r.status_code}: {r.text[:300]}")
        return False
    return True

BATCH = 50
ok = 0
for i in range(0, len(all_rows), BATCH):
    batch = all_rows[i:i+BATCH]
    if upsert_batch(batch):
        ok += len(batch)
        print(f"  Tuotu {ok}/{len(all_rows)}…")
    else:
        print(f"  Erä {i//BATCH+1} epäonnistui")

print(f"\nValmis! {ok}/{len(all_rows)} prospektia tuotu Supabaseen.")
