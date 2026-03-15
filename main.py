"""
Spara Energia Oy – Kiinteistörekisteri
Hakee Suomen pientalojen tiedot postinumeroaluetasolla (~3 000 riviä)
Tilastokeskuksen Paavo- ja StatFin-rajapinnoista, tallentaa Supabaseen ja CSV:hen.
"""

import csv
import itertools
import json
import logging
import math
import os
import time
from datetime import date
from typing import Optional

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Konfiguraatio
# ---------------------------------------------------------------------------

PAAVO_BASE = (
    "https://pxdata.stat.fi/PxWeb/api/v1/fi/"
    "Postinumeroalueittainen_avoin_tieto/"
    "Postinumeroalueittainen_avoin_tieto__uusin"
)
RAKKE_BASE = "https://pxdata.stat.fi/PxWeb/api/v1/fi/StatFin/StatFin__rakke"

SUPABASE_URL = "https://yywoyzysgjkhhwveroeb.supabase.co"
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl5d295enlzZ2praGh3dmVyb2ViIiwicm9sZSI6"
    "InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzU3OTYxMCwiZXhwIjoyMDg5MTU1NjEwfQ."
    "GUBNhSyrlOwLf07SOSUUXqZP5kMK7H_XcEZvR1_O36c",
)
TABLE_NAME = "area_profiles"
BATCH_SIZE = 500
RATE_SLEEP = 7.0   # ~8 kyselyä/min (alle 10/min limit)
OUTPUT_CSV = "spara_kiinteistorekisteri.csv"
TODAY = date.today().isoformat()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kerros 0 – HTTP-apufunktiot
# ---------------------------------------------------------------------------


def _rate_sleep():
    time.sleep(RATE_SLEEP)


def px_get(url: str) -> dict:
    """GET PxWeb-metadata. Käsittelee 429 Retry-After-headerilla."""
    _rate_sleep()
    for attempt in range(4):
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            log.warning("429 – odotetaan %ds (yritys %d/4)", wait, attempt + 1)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"GET epäonnistui 4 yrityksen jälkeen: {url}")


def px_post(url: str, body: dict) -> dict:
    """POST PxWeb-kysely json-stat2-muodossa."""
    body["response"] = {"format": "json-stat2"}
    _rate_sleep()
    for attempt in range(4):
        resp = requests.post(url, json=body, headers=HEADERS, timeout=120)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            log.warning("429 – odotetaan %ds (yritys %d/4)", wait, attempt + 1)
            time.sleep(wait)
            continue
        if not resp.ok:
            log.error("HTTP %d: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"POST epäonnistui 4 yrityksen jälkeen: {url}")


def parse_jsonstat2(data: dict) -> pd.DataFrame:
    """
    Muuntaa PxWebin palauttaman json-stat2-kuution DataFrameksi.
    Toimii standardin JSON-stat2-skeeman kanssa.
    """
    # Tuetaan sekä dataset-wrap että suora rakenne
    if "dataset" in data:
        ds = data["dataset"]
    else:
        ds = data

    dims = ds["dimension"]
    dim_ids = ds["id"]
    dim_sizes = ds["size"]
    values = ds["value"]

    # Rakenna jokaisen dimension arvolista järjestyksessä
    dim_value_lists = []
    for d_id in dim_ids:
        cats = dims[d_id]["category"]
        # index voi olla dict tai lista – normalisoi listaksi järjestyksessä
        if "index" in cats:
            idx = cats["index"]
            if isinstance(idx, dict):
                ordered = sorted(idx.keys(), key=lambda k: idx[k])
            else:
                ordered = list(idx)
        else:
            ordered = list(cats["label"].keys())
        dim_value_lists.append(ordered)

    rows = []
    for coord, val in zip(itertools.product(*dim_value_lists), values):
        row = dict(zip(dim_ids, coord))
        row["_value"] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    # Lisää label-sarakkeet (luettavat nimet) jokaiselle dimensiolle
    for d_id in dim_ids:
        cats = dims[d_id]["category"]
        labels = cats.get("label", {})
        df[d_id + "_label"] = df[d_id].map(labels)

    return df


def supabase_upsert(rows: list[dict], table: str = TABLE_NAME) -> None:
    """Kirjoita rivit Supabaseen erissä, upsert postinumeron perusteella."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    hdrs = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    total = len(rows)
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        resp = requests.post(url, json=batch, headers=hdrs, timeout=60)
        if not resp.ok:
            log.error("Supabase virhe %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        log.info(
            "Supabase upsert: erä %d/%d (%d riviä)",
            i // BATCH_SIZE + 1,
            math.ceil(total / BATCH_SIZE),
            len(batch),
        )


# ---------------------------------------------------------------------------
# Kerros 1 – Datahaku: Paavo
# ---------------------------------------------------------------------------


def _discover_tiedot_codes(meta: dict, keywords: list[str]) -> list[str]:
    """
    Etsii Tiedot-dimension koodit joiden label sisältää jonkin keywords-sanan.
    Case-insensitive. Palauttaa löydettyjen koodien listan.
    """
    for var in meta.get("variables", []):
        if var.get("code", "").lower() in ("tiedot", "contents"):
            codes = var.get("values", [])
            labels = var.get("valueTexts", codes)
            result = []
            for code, label in zip(codes, labels):
                label_low = label.lower()
                if any(kw.lower() in label_low for kw in keywords):
                    result.append(code)
            return result
    return []


def fetch_paavo_buildings() -> pd.DataFrame:
    """
    Hakee Paavo-tietokannasta rakennustiedot kaikille postinumeroalueille.
    Palauttaa: postinumero, postitoimipaikka, pientalot_lkm, rivitalot_lkm,
               keskim_kerrosala_m2
    """
    url = f"{PAAVO_BASE}/paavo_pxt_12f4.px"
    log.info("Haetaan Paavo rakennustiedot (metadata)...")
    meta = px_get(url)

    # Selvitä postinumero-dimension koodi
    posti_code = None
    tiedot_code = None
    for var in meta.get("variables", []):
        code_low = var.get("code", "").lower()
        if "postinumero" in code_low or "postal" in code_low:
            posti_code = var["code"]
        if code_low in ("tiedot", "contents"):
            tiedot_code = var["code"]

    if not posti_code:
        posti_code = meta["variables"][0]["code"]
    if not tiedot_code:
        tiedot_code = meta["variables"][-1]["code"]

    log.info("Paavo rakennukset – dimensiot: postinumero=%s, tiedot=%s", posti_code, tiedot_code)

    # Selvitä käytettävissä olevat Tiedot-koodit
    pientalo_kws = ["pientalo", "erillinen", "pientaloasunto", "rivi", "small", "detached"]
    rivitalo_kws = ["rivi", "ketju", "row", "terraced"]
    kerrosala_kws = ["kerrosala", "pinta-ala", "floor", "area", "m2", "neliö"]

    all_tiedot = []
    tiedot_labels = {}
    for var in meta.get("variables", []):
        if var.get("code") == tiedot_code:
            all_tiedot = var.get("values", [])
            tiedot_texts = var.get("valueTexts", all_tiedot)
            tiedot_labels = dict(zip(all_tiedot, tiedot_texts))
            break

    log.info("Paavo Tiedot-koodit: %s", tiedot_labels)

    # Valitse kaikki koodit – suodatetaan jälkikäteen
    body = {
        "query": [
            {
                "code": posti_code,
                "selection": {"filter": "all", "values": ["*"]},
            },
            {
                "code": tiedot_code,
                "selection": {"filter": "all", "values": ["*"]},
            },
        ]
    }

    log.info("Haetaan Paavo rakennustiedot (data)...")
    raw = px_post(url, body)
    df = parse_jsonstat2(raw)
    log.info("Paavo rakennukset: %d riviä haettu", len(df))

    # Pivot: yksi rivi per postinumero
    df = df.rename(columns={posti_code: "postinumero", tiedot_code: "tiedot_koodi"})
    df["postinumero_label"] = df.get("postinumero_label", df["postinumero"])

    pivot = df.pivot_table(
        index=["postinumero", "postinumero_label"],
        columns="tiedot_koodi",
        values="_value",
        aggfunc="first",
    ).reset_index()
    pivot.columns.name = None

    log.info("Paavo rakennukset pivot-sarakkeet: %s", list(pivot.columns))

    # Nimeä sarakkeet tuttuihin muuttujiin
    # Tunnista sarakkeet label-tekstin perusteella
    def find_col(df_cols, keywords):
        for kw in keywords:
            for c in df_cols:
                if kw.lower() in str(c).lower():
                    return c
        return None

    cols = list(pivot.columns)
    pt_col = find_col(cols, ["pientalo", "erillinen pientalo", "detached"])
    rt_col = find_col(cols, ["rivi", "ketju"])
    ka_col = find_col(cols, ["kerrosala", "keskipinta", "floor area", "asunnon pinta"])

    log.info("Tunnistetut sarakkeet: pientalo=%s, rivitalo=%s, kerrosala=%s", pt_col, rt_col, ka_col)

    result = pd.DataFrame()
    result["postinumero"] = pivot["postinumero"].astype(str).str.zfill(5)
    # postitoimipaikka: nimi postinumero_label-kentästä (esim. "00100 Helsinki")
    result["postitoimipaikka"] = pivot["postinumero_label"].apply(
        lambda x: str(x).split(" ", 1)[1].strip() if " " in str(x) else str(x)
    )
    result["pientalot_lkm"] = pd.to_numeric(pivot[pt_col], errors="coerce").fillna(0).astype(int) if pt_col else 0
    result["rivitalot_lkm"] = pd.to_numeric(pivot[rt_col], errors="coerce").fillna(0).astype(int) if rt_col else 0
    result["keskim_kerrosala_m2"] = pd.to_numeric(pivot[ka_col], errors="coerce") if ka_col else None

    return result


def fetch_paavo_population() -> pd.DataFrame:
    """
    Hakee Paavo-tietokannasta väestötiedot → kunta-mapping.
    Palauttaa: postinumero, vaesto_lkm, kunta_nimi
    """
    url = f"{PAAVO_BASE}/paavo_pxt_12ey.px"
    log.info("Haetaan Paavo väestötiedot (metadata)...")
    meta = px_get(url)

    posti_code = None
    tiedot_code = None
    kunta_code = None
    for var in meta.get("variables", []):
        code_low = var.get("code", "").lower()
        if "postinumero" in code_low:
            posti_code = var["code"]
        elif code_low in ("tiedot", "contents"):
            tiedot_code = var["code"]
        elif "kunta" in code_low:
            kunta_code = var["code"]

    if not posti_code:
        posti_code = meta["variables"][0]["code"]

    log.info("Paavo väestö – dimensiot: postinumero=%s, tiedot=%s, kunta=%s",
             posti_code, tiedot_code, kunta_code)

    # Hae kaikki tiedot
    body = {
        "query": [
            {
                "code": posti_code,
                "selection": {"filter": "all", "values": ["*"]},
            },
        ]
    }
    if tiedot_code:
        # Hae vain väkiluku
        tiedot_all = []
        for var in meta.get("variables", []):
            if var.get("code") == tiedot_code:
                tiedot_all = var.get("values", [])
                break
        vaesto_codes = [c for c in tiedot_all if "vaesto" in c.lower() or "he_vakiy" in c.lower() or "he_" in c.lower()]
        if not vaesto_codes:
            vaesto_codes = [tiedot_all[0]] if tiedot_all else []
        if vaesto_codes:
            body["query"].append({
                "code": tiedot_code,
                "selection": {"filter": "item", "values": vaesto_codes[:1]},
            })

    log.info("Haetaan Paavo väestötiedot (data)...")
    raw = px_post(url, body)
    df = parse_jsonstat2(raw)
    log.info("Paavo väestö: %d riviä", len(df))

    df = df.rename(columns={posti_code: "postinumero"})
    result = pd.DataFrame()
    result["postinumero"] = df["postinumero"].astype(str).str.zfill(5)

    # Kunta_nimi postinumeron labelista: "00100 Helsinki" → "Helsinki"
    label_col = "postinumero_label"
    if label_col in df.columns:
        result["kunta_nimi"] = df[label_col].apply(_extract_kunta_from_label)
    else:
        result["kunta_nimi"] = None

    # Väkiluku
    val_col = "_value"
    if val_col in df.columns:
        result["vaesto_lkm"] = pd.to_numeric(df[val_col], errors="coerce").fillna(0).astype(int)
    else:
        result["vaesto_lkm"] = 0

    # Deduplicate: jos useita Tiedot-rivejä per postinumero, ota ensimmäinen
    result = result.drop_duplicates(subset=["postinumero"])
    return result


def _extract_kunta_from_label(label: str) -> str:
    """
    Hakee kuntanimen Paavo postinumero-labelista.
    Muoto: "00100 Helsinki" tai "02940 Espoo" tai "TUNTEMATON".
    """
    s = str(label).strip()
    # Muoto: "NNNNN Kuntanimi" tai "NNNNN KUNTANIMI"
    parts = s.split(" ", 1)
    if len(parts) == 2:
        return parts[1].strip().title()
    return s


# ---------------------------------------------------------------------------
# Kerros 1 – Datahaku: StatFin rakke
# ---------------------------------------------------------------------------

# Käyttötarkoituskoodit: pientalot
PIENTALO_CODES = ["0110", "0111", "0112", "0113"]


def _fetch_rakke_table(table_name: str, extra_dims: list[dict], year: str) -> pd.DataFrame:
    """
    Yleinen haku StatFin rakke -taulusta. extra_dims sisältää
    lisädimensioiden query-objektit.
    """
    url = f"{RAKKE_BASE}/{table_name}"
    log.info("Haetaan %s (metadata)...", table_name)
    meta = px_get(url)

    # Tunnista dimensiokoodit
    dim_map = {}
    latest_year = year
    for var in meta.get("variables", []):
        code = var["code"]
        code_low = code.lower()
        dim_map[code_low] = var
        # Selvitä viimeisin vuosi
        if "vuosi" in code_low or code_low == "year":
            years_avail = var.get("values", [])
            if years_avail:
                latest_year = years_avail[-1]

    log.info("%s – käytetään vuotta: %s", table_name, latest_year)
    log.info("%s – dimensiot: %s", table_name, list(dim_map.keys()))

    # Etsi Alue- ja Vuosi-dimensioiden koodit
    alue_code = None
    vuosi_code = None
    for var in meta["variables"]:
        c = var["code"].lower()
        if c in ("alue", "region", "area"):
            alue_code = var["code"]
        elif c in ("vuosi", "year"):
            vuosi_code = var["code"]

    if not alue_code:
        # Ota ensimmäinen dimensio
        alue_code = meta["variables"][0]["code"]
    if not vuosi_code:
        for var in meta["variables"]:
            if "vuosi" in var["code"].lower() or "year" in var["code"].lower():
                vuosi_code = var["code"]
                break

    query = []
    if alue_code:
        query.append({
            "code": alue_code,
            "selection": {"filter": "all", "values": ["*"]},
        })
    if vuosi_code:
        query.append({
            "code": vuosi_code,
            "selection": {"filter": "item", "values": [latest_year]},
        })
    query.extend(extra_dims)

    body = {"query": query}
    log.info("Haetaan %s (data)...", table_name)
    raw = px_post(url, body)
    df = parse_jsonstat2(raw)
    log.info("%s: %d riviä haettu", table_name, len(df))

    # Lisää alue_code jos puuttuu nimestä
    if alue_code:
        df = df.rename(columns={alue_code: "alue_koodi"})
        if alue_code + "_label" in df.columns:
            df = df.rename(columns={alue_code + "_label": "kunta_nimi"})
    if vuosi_code:
        df = df.rename(columns={vuosi_code: "vuosi"})

    return df, meta


def fetch_rakke_heating(year: str = "2023") -> pd.DataFrame:
    """
    Hakee lämmitysainejakauman kunnittain pientaloille.
    Palauttaa: kunta_nimi, lammitysaine_koodi, lammitysaine_nimi, rakennusten_lkm
    """
    table = "statfin_rakke_pxt_116h.px"
    url = f"{RAKKE_BASE}/{table}"
    meta = px_get(url)

    # Tunnista käyttötarkoitus- ja lämmitysaine-dimensiot
    kaytto_code = None
    lammi_code = None
    alue_code = None
    vuosi_code = None
    latest_year = year

    for var in meta["variables"]:
        c = var["code"].lower()
        lbl = var.get("text", "").lower()
        if "käyttötarkoitus" in lbl or "kayttotarkoitus" in c or "use" in c:
            kaytto_code = var["code"]
        elif "lämmitysaine" in lbl or "lammitysaine" in c or "heating" in c or "fuel" in c:
            lammi_code = var["code"]
        elif c in ("alue", "region"):
            alue_code = var["code"]
        elif c in ("vuosi", "year"):
            vuosi_code = var["code"]
            years_avail = var.get("values", [])
            if years_avail:
                latest_year = years_avail[-1]

    log.info("rakke_116h – käyttötarkoitus=%s, lämmitysaine=%s, vuosi=%s",
             kaytto_code, lammi_code, latest_year)

    extra = []
    if kaytto_code:
        # Hae kaikki käyttötarkoitukset ja suodata pientalot jälkikäteen
        extra.append({
            "code": kaytto_code,
            "selection": {"filter": "all", "values": ["*"]},
        })
    if lammi_code:
        extra.append({
            "code": lammi_code,
            "selection": {"filter": "all", "values": ["*"]},
        })

    df, _ = _fetch_rakke_table(table, extra, latest_year)

    # Uudelleennimeä sarakkeet
    if kaytto_code and kaytto_code in df.columns:
        df = df.rename(columns={
            kaytto_code: "kayttotarkoitus_koodi",
            kaytto_code + "_label": "kayttotarkoitus_nimi",
        })
    if lammi_code and lammi_code in df.columns:
        df = df.rename(columns={
            lammi_code: "lammitysaine_koodi",
            lammi_code + "_label": "lammitysaine_nimi",
        })

    df = df.rename(columns={"_value": "rakennusten_lkm"})

    # Suodata pientalot (0110, 0111, 0112, 0113) ja pois SSS (koko maa)
    if "kayttotarkoitus_koodi" in df.columns:
        df = df[df["kayttotarkoitus_koodi"].isin(PIENTALO_CODES)]
    if "alue_koodi" in df.columns:
        df = df[df["alue_koodi"] != "SSS"]

    df["rakennusten_lkm"] = pd.to_numeric(df["rakennusten_lkm"], errors="coerce").fillna(0)
    return df


def fetch_rakke_construction_year(year: str = "2023") -> pd.DataFrame:
    """
    Hakee rakennusvuosijakauman kunnittain pientaloille.
    Palauttaa: kunta_nimi, rakennusvuosi_luokka, rakennusten_lkm
    """
    table = "statfin_rakke_pxt_116g.px"
    url = f"{RAKKE_BASE}/{table}"
    meta = px_get(url)

    kaytto_code = None
    rvuosi_code = None
    latest_year = year

    for var in meta["variables"]:
        c = var["code"].lower()
        lbl = var.get("text", "").lower()
        if "käyttötarkoitus" in lbl or "kayttotarkoitus" in c:
            kaytto_code = var["code"]
        elif "rakennusvuosi" in lbl or "rakennusvuosi" in c or "construction" in c:
            rvuosi_code = var["code"]
        elif c in ("vuosi", "year"):
            years_avail = var.get("values", [])
            if years_avail:
                latest_year = years_avail[-1]

    log.info("rakke_116g – käyttötarkoitus=%s, rakennusvuosi=%s, vuosi=%s",
             kaytto_code, rvuosi_code, latest_year)

    extra = []
    if kaytto_code:
        extra.append({
            "code": kaytto_code,
            "selection": {"filter": "all", "values": ["*"]},
        })
    if rvuosi_code:
        extra.append({
            "code": rvuosi_code,
            "selection": {"filter": "all", "values": ["*"]},
        })

    df, _ = _fetch_rakke_table(table, extra, latest_year)

    if kaytto_code and kaytto_code in df.columns:
        df = df.rename(columns={
            kaytto_code: "kayttotarkoitus_koodi",
            kaytto_code + "_label": "kayttotarkoitus_nimi",
        })
    if rvuosi_code and rvuosi_code in df.columns:
        df = df.rename(columns={
            rvuosi_code: "rakennusvuosi_luokka",
            rvuosi_code + "_label": "rakennusvuosi_nimi",
        })

    df = df.rename(columns={"_value": "rakennusten_lkm"})

    if "kayttotarkoitus_koodi" in df.columns:
        df = df[df["kayttotarkoitus_koodi"].isin(PIENTALO_CODES)]
    if "alue_koodi" in df.columns:
        df = df[df["alue_koodi"] != "SSS"]

    df["rakennusten_lkm"] = pd.to_numeric(df["rakennusten_lkm"], errors="coerce").fillna(0)
    return df


def fetch_rakke_material(year: str = "2023") -> pd.DataFrame:
    """
    Hakee rakennusainejakauman kunnittain pientaloille.
    Palauttaa: kunta_nimi, rakennusaine_koodi, rakennusaine_nimi, rakennusten_lkm
    """
    table = "statfin_rakke_pxt_116i.px"
    url = f"{RAKKE_BASE}/{table}"
    meta = px_get(url)

    kaytto_code = None
    aine_code = None
    latest_year = year

    for var in meta["variables"]:
        c = var["code"].lower()
        lbl = var.get("text", "").lower()
        if "käyttötarkoitus" in lbl or "kayttotarkoitus" in c:
            kaytto_code = var["code"]
        elif "rakennusaine" in lbl or "rakennusaine" in c or "material" in c or "aine" in c:
            aine_code = var["code"]
        elif c in ("vuosi", "year"):
            years_avail = var.get("values", [])
            if years_avail:
                latest_year = years_avail[-1]

    log.info("rakke_116i – käyttötarkoitus=%s, rakennusaine=%s, vuosi=%s",
             kaytto_code, aine_code, latest_year)

    extra = []
    if kaytto_code:
        extra.append({
            "code": kaytto_code,
            "selection": {"filter": "all", "values": ["*"]},
        })
    if aine_code:
        extra.append({
            "code": aine_code,
            "selection": {"filter": "all", "values": ["*"]},
        })

    df, _ = _fetch_rakke_table(table, extra, latest_year)

    if kaytto_code and kaytto_code in df.columns:
        df = df.rename(columns={
            kaytto_code: "kayttotarkoitus_koodi",
            kaytto_code + "_label": "kayttotarkoitus_nimi",
        })
    if aine_code and aine_code in df.columns:
        df = df.rename(columns={
            aine_code: "rakennusaine_koodi",
            aine_code + "_label": "rakennusaine_nimi",
        })

    df = df.rename(columns={"_value": "rakennusten_lkm"})

    if "kayttotarkoitus_koodi" in df.columns:
        df = df[df["kayttotarkoitus_koodi"].isin(PIENTALO_CODES)]
    if "alue_koodi" in df.columns:
        df = df[df["alue_koodi"] != "SSS"]

    df["rakennusten_lkm"] = pd.to_numeric(df["rakennusten_lkm"], errors="coerce").fillna(0)
    return df


# ---------------------------------------------------------------------------
# Kerros 2 – Kunta-aggregaatit
# ---------------------------------------------------------------------------


def compute_municipality_heating_shares(df: pd.DataFrame) -> pd.DataFrame:
    """
    Laskee lämmitysaineprosentit kunnittain.
    Palauttaa: kunta_nimi + [kaukolampo_pct, oljy_pct, sahko_pct,
                              maalampo_pct, puu_pct, muu_pct]
    """
    if df.empty or "lammitysaine_nimi" not in df.columns:
        return pd.DataFrame()

    # Normalisoi lämmitysaineiden nimet kategoriaksi
    def _kategorisoi_lammitys(nimi: str) -> str:
        n = str(nimi).lower()
        if "kaukolämpö" in n or "kaukolampo" in n or "district" in n:
            return "kaukolampo"
        elif "öljy" in n or "oljy" in n or "oil" in n or "kaasu" in n or "gas" in n:
            return "oljy"
        elif "sähkö" in n or "sahko" in n or "electric" in n:
            return "sahko"
        elif "maalämpö" in n or "maalampo" in n or "lämpöpumppu" in n or "heat pump" in n or "geo" in n:
            return "maalampo"
        elif "puu" in n or "biomassa" in n or "hake" in n or "pellet" in n or "wood" in n:
            return "puu"
        else:
            return "muu"

    df2 = df.copy()
    df2["lammi_kat"] = df2["lammitysaine_nimi"].apply(_kategorisoi_lammitys)

    grp = df2.groupby(["kunta_nimi", "lammi_kat"])["rakennusten_lkm"].sum().unstack(fill_value=0).reset_index()

    for cat in ["kaukolampo", "oljy", "sahko", "maalampo", "puu", "muu"]:
        if cat not in grp.columns:
            grp[cat] = 0

    grp["total"] = grp[["kaukolampo", "oljy", "sahko", "maalampo", "puu", "muu"]].sum(axis=1)

    for cat in ["kaukolampo", "oljy", "sahko", "maalampo", "puu", "muu"]:
        grp[cat + "_pct"] = (grp[cat] / grp["total"].replace(0, float("nan")) * 100).round(1)
        grp[cat + "_lkm_kunta"] = grp[cat]

    result = grp[
        ["kunta_nimi", "kaukolampo_pct", "oljy_pct", "sahko_pct",
         "maalampo_pct", "puu_pct", "muu_pct",
         "kaukolampo_lkm_kunta", "oljy_lkm_kunta", "sahko_lkm_kunta",
         "maalampo_lkm_kunta", "puu_lkm_kunta", "muu_lkm_kunta", "total"]
    ].copy()
    return result


def compute_municipality_construction_year_shares(df: pd.DataFrame) -> pd.DataFrame:
    """
    Laskee rakennusvuosiprosentit kunnittain.
    Palauttaa: kunta_nimi + [ennen_1970_pct, v1970_1999_pct, v2000_jalkeen_pct]
    """
    if df.empty:
        return pd.DataFrame()

    year_col = "rakennusvuosi_luokka" if "rakennusvuosi_luokka" in df.columns else None
    if not year_col:
        return pd.DataFrame()

    def _kategoria(luokka: str) -> str:
        s = str(luokka)
        # Tunnista vuosiluvut luokan koodista tai nimestä
        # Tilastokeskuksen tyypilliset luokat: "-1959", "1960-1969", "1970-1979", ...
        # tai koodit kuten "1", "2", ...
        nums = [int(x) for x in __import__("re").findall(r"\d{4}", s)]
        if not nums:
            return "tuntematon"
        yr = nums[0]
        if yr < 1970:
            return "ennen_1970"
        elif yr <= 1999:
            return "v1970_1999"
        else:
            return "v2000_jalkeen"

    df2 = df.copy()
    df2["vuosi_kat"] = df2[year_col].apply(_kategoria)
    df2 = df2[df2["vuosi_kat"] != "tuntematon"]

    grp = df2.groupby(["kunta_nimi", "vuosi_kat"])["rakennusten_lkm"].sum().unstack(fill_value=0).reset_index()

    for cat in ["ennen_1970", "v1970_1999", "v2000_jalkeen"]:
        if cat not in grp.columns:
            grp[cat] = 0

    grp["total"] = grp[["ennen_1970", "v1970_1999", "v2000_jalkeen"]].sum(axis=1)
    for cat in ["ennen_1970", "v1970_1999", "v2000_jalkeen"]:
        grp[cat + "_pct"] = (grp[cat] / grp["total"].replace(0, float("nan")) * 100).round(1)

    return grp[["kunta_nimi", "ennen_1970_pct", "v1970_1999_pct", "v2000_jalkeen_pct"]].copy()


def compute_municipality_material_shares(df: pd.DataFrame) -> pd.DataFrame:
    """
    Laskee rakennusaineprosentit kunnittain.
    Palauttaa: kunta_nimi + [puu_osuus_pct, kivi_osuus_pct]
    """
    if df.empty:
        return pd.DataFrame()

    aine_col = "rakennusaine_nimi" if "rakennusaine_nimi" in df.columns else None
    if not aine_col:
        return pd.DataFrame()

    def _kategorisoi_aine(nimi: str) -> str:
        n = str(nimi).lower()
        if "puu" in n or "wood" in n or "timber" in n:
            return "puu"
        elif any(x in n for x in ["kivi", "betoni", "tiili", "concrete", "brick", "stone"]):
            return "kivi"
        else:
            return "muu"

    df2 = df.copy()
    df2["aine_kat"] = df2[aine_col].apply(_kategorisoi_aine)

    grp = df2.groupby(["kunta_nimi", "aine_kat"])["rakennusten_lkm"].sum().unstack(fill_value=0).reset_index()

    for cat in ["puu", "kivi", "muu"]:
        if cat not in grp.columns:
            grp[cat] = 0

    grp["total"] = grp[["puu", "kivi", "muu"]].sum(axis=1)
    grp["puu_osuus_pct"] = (grp["puu"] / grp["total"].replace(0, float("nan")) * 100).round(1)
    grp["kivi_osuus_pct"] = (grp["kivi"] / grp["total"].replace(0, float("nan")) * 100).round(1)

    return grp[["kunta_nimi", "puu_osuus_pct", "kivi_osuus_pct"]].copy()


def compute_municipality_population(pop_df: pd.DataFrame) -> pd.DataFrame:
    """
    Laskee kuntakohtaisen väkiluvun (esg_raportointi_tarve-laskentaan).
    Palauttaa: kunta_nimi, kunta_vakiluku
    """
    if pop_df.empty or "kunta_nimi" not in pop_df.columns:
        return pd.DataFrame()
    grp = pop_df.groupby("kunta_nimi")["vaesto_lkm"].sum().reset_index()
    grp.columns = ["kunta_nimi", "kunta_vakiluku"]
    return grp


# ---------------------------------------------------------------------------
# Kerros 3 – Yhdistäminen ja jakelu
# ---------------------------------------------------------------------------


def merge_all(
    buildings_df: pd.DataFrame,
    pop_df: pd.DataFrame,
    heating_shares: pd.DataFrame,
    year_shares: pd.DataFrame,
    material_shares: pd.DataFrame,
    kunta_pop: pd.DataFrame,
) -> pd.DataFrame:
    """
    Yhdistää kaikki DataFramet. Jakaa kuntatason prosentit postinumeroalueiden
    rakennusmääriin.
    """
    df = buildings_df.copy()

    # Lisää kunta_nimi väestödatasta
    if not pop_df.empty and "kunta_nimi" in pop_df.columns:
        pop_slim = pop_df[["postinumero", "kunta_nimi", "vaesto_lkm"]].drop_duplicates("postinumero")
        df = df.merge(pop_slim, on="postinumero", how="left")
    else:
        df["kunta_nimi"] = None
        df["vaesto_lkm"] = 0

    # Liitä lämmitysprosentit
    if not heating_shares.empty:
        df = df.merge(heating_shares, on="kunta_nimi", how="left")
    else:
        for col in ["kaukolampo_pct", "oljy_pct", "sahko_pct", "maalampo_pct", "puu_pct", "muu_pct"]:
            df[col] = None

    # Liitä rakennusvuosiprosentit
    if not year_shares.empty:
        df = df.merge(year_shares, on="kunta_nimi", how="left")
    else:
        for col in ["ennen_1970_pct", "v1970_1999_pct", "v2000_jalkeen_pct"]:
            df[col] = None

    # Liitä rakennusaineprosentit
    if not material_shares.empty:
        df = df.merge(material_shares, on="kunta_nimi", how="left")
    else:
        df["puu_osuus_pct"] = None
        df["kivi_osuus_pct"] = None

    # Liitä kuntaväkiluku
    if not kunta_pop.empty:
        df = df.merge(kunta_pop, on="kunta_nimi", how="left")
    else:
        df["kunta_vakiluku"] = 0

    # Laske estimoidut absoluuttiset luvut kuntatason prosenteista
    total_col = df["pientalot_lkm"] + df["rivitalot_lkm"]

    def _estimate(pct_col: str) -> pd.Series:
        if pct_col not in df.columns:
            return pd.Series(0, index=df.index)
        return (df[pct_col].fillna(0) / 100 * total_col).round().fillna(0).astype(int)

    df["kaukolampo_lkm"]     = _estimate("kaukolampo_pct")
    df["oilheat_lkm"]        = _estimate("oljy_pct")
    df["sahkolammitys_lkm"]  = _estimate("sahko_pct")
    df["maalampo_lkm"]       = _estimate("maalampo_pct")
    df["puulammitys_lkm"]    = _estimate("puu_pct")
    df["muu_lammitys_lkm"]   = _estimate("muu_pct")

    df["rakennettu_ennen_1970"]   = _estimate("ennen_1970_pct")
    df["rakennettu_1970_1999"]    = _estimate("v1970_1999_pct")
    df["rakennettu_2000_jalkeen"] = _estimate("v2000_jalkeen_pct")

    # Luotettavuus
    df["luotettavuus_1_5"] = df["pientalot_lkm"].apply(lambda x: 1 if x < 10 else 3)

    return df


# ---------------------------------------------------------------------------
# Kerros 4 – Johdetut sarakkeet
# ---------------------------------------------------------------------------


def _safe_pct(num, denom) -> Optional[float]:
    try:
        if denom and denom > 0:
            return round(float(num) / float(denom) * 100, 1)
    except (TypeError, ZeroDivisionError, ValueError):
        pass
    return None


def add_calculated_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lisää kaikki liiketoimintalogiiikan sarakkeet."""
    df = df.copy()

    total = df["pientalot_lkm"] + df["rivitalot_lkm"]

    # Osuusprosentit
    df["oljy_osuus_pct"] = df.apply(
        lambda r: _safe_pct(r["oilheat_lkm"], r["pientalot_lkm"] + r["rivitalot_lkm"]), axis=1
    )
    sahko_osuus = df.apply(
        lambda r: _safe_pct(r["sahkolammitys_lkm"], r["pientalot_lkm"] + r["rivitalot_lkm"]), axis=1
    )

    ennen_1970_pct = df.apply(
        lambda r: _safe_pct(r["rakennettu_ennen_1970"],
                            r["pientalot_lkm"] + r["rivitalot_lkm"]), axis=1
    )

    # transitio_potentiaali
    def _transitio(row) -> str:
        oljy = row["oljy_osuus_pct"] or 0
        en70 = ennen_1970_pct.loc[row.name] or 0
        if oljy > 20 or en70 > 50:
            return "KORKEA"
        elif (10 <= oljy <= 20) or (30 <= en70 <= 50):
            return "KESKITASO"
        return "MATALA"

    df["transitio_potentiaali"] = df.apply(_transitio, axis=1)

    # pankkikumppani_arvo
    df["pankkikumppani_arvo"] = df["pientalot_lkm"].apply(
        lambda x: "KORKEA" if x > 500 else ("KESKITASO" if x >= 100 else "MATALA")
    )

    # vakuutus_arvo
    def _vakuutus(row) -> str:
        en70 = ennen_1970_pct.loc[row.name] or 0
        oljy = row["oljy_osuus_pct"] or 0
        a = en70 > 50
        b = oljy > 15
        if a and b:
            return "KORKEA"
        elif a or b:
            return "KESKITASO"
        return "MATALA"

    df["vakuutus_arvo"] = df.apply(_vakuutus, axis=1)

    # energiayhtio_arvo
    df["energiayhtio_arvo"] = sahko_osuus.apply(
        lambda x: "KORKEA" if (x or 0) > 40 else ("KESKITASO" if (x or 0) >= 20 else "MATALA")
    )

    # esg_raportointi_tarve
    df["esg_raportointi_tarve"] = df["kunta_vakiluku"].apply(
        lambda x: "KORKEA" if (x or 0) > 50000 else ("KESKITASO" if (x or 0) >= 10000 else "MATALA")
    )

    # jousto_potentiaali_mw
    df["jousto_potentiaali_mw"] = (
        (df["sahkolammitys_lkm"].fillna(0) * 3 + df["maalampo_lkm"].fillna(0) * 2) / 1000
    ).round(2)

    # Potentiaalit
    df["oljykorvaus_potentiaali"]  = df["oilheat_lkm"]
    df["sahko_optimointi_pot"]     = df["sahkolammitys_lkm"]
    df["lp_potentiaali"]           = (df["pientalot_lkm"] - df["kaukolampo_lkm"]).clip(lower=0)
    df["aurinkopaneeli_pot"]       = df["pientalot_lkm"]
    df["spara_tam_alue"]           = total

    # Metadata
    df["lahde"]      = "Tilastokeskus Paavo + StatFin rakke (CC BY 4.0)"
    df["paivitetty"] = TODAY

    huomiot_base = "maalampo_aliarvio: VTJ päivittyy vain rakennusluvilla"
    df["huomiot"] = df.apply(
        lambda r: huomiot_base + "; matala_luotettavuus: alle 10 pientaloa"
        if r["luotettavuus_1_5"] == 1
        else huomiot_base,
        axis=1,
    )

    # ET-sarakkeet → NULL
    for col in ["et_todistuksia_lkm", "et_peitto_pct", "et_keskim_luokka",
                "et_a_b_osuus_pct", "et_e_g_osuus_pct", "e_luku_keskim"]:
        df[col] = None

    return df


# ---------------------------------------------------------------------------
# Kerros 5 – Tulostus
# ---------------------------------------------------------------------------


# Sarakkeet täsmälleen Supabase-skeeman mukaisessa järjestyksessä
SUPABASE_COLS = [
    "postinumero", "postitoimipaikka", "kunta", "maakunta",
    "pientalot_lkm", "rivitalot_lkm",
    "rakennettu_ennen_1970", "rakennettu_1970_1999", "rakennettu_2000_jalkeen",
    "puu_osuus_pct", "kivi_osuus_pct", "keskim_kerrosala_m2",
    "oilheat_lkm", "sahkolammitys_lkm", "kaukolampo_lkm",
    "maalampo_lkm", "puulammitys_lkm", "muu_lammitys_lkm",
    "oljy_osuus_pct",
    "et_todistuksia_lkm", "et_peitto_pct", "et_keskim_luokka",
    "et_a_b_osuus_pct", "et_e_g_osuus_pct", "e_luku_keskim",
    "transitio_potentiaali", "oljykorvaus_potentiaali",
    "sahko_optimointi_pot", "lp_potentiaali", "aurinkopaneeli_pot",
    "spara_tam_alue",
    "pankkikumppani_arvo", "vakuutus_arvo", "energiayhtio_arvo",
    "esg_raportointi_tarve", "jousto_potentiaali_mw",
    "lahde", "paivitetty", "luotettavuus_1_5", "huomiot",
]


def _build_output_df(df: pd.DataFrame) -> pd.DataFrame:
    """Rakentaa tulosDataFramen oikeilla sarakkeilla."""
    out = pd.DataFrame()
    out["postinumero"]      = df["postinumero"]
    out["postitoimipaikka"] = df.get("postitoimipaikka", None)
    out["kunta"]            = df.get("kunta_nimi", None)
    out["maakunta"]         = df.get("maakunta", None)

    for col in ["pientalot_lkm", "rivitalot_lkm",
                "rakennettu_ennen_1970", "rakennettu_1970_1999", "rakennettu_2000_jalkeen"]:
        out[col] = df.get(col, 0)

    out["puu_osuus_pct"]        = df.get("puu_osuus_pct", None)
    out["kivi_osuus_pct"]       = df.get("kivi_osuus_pct", None)
    out["keskim_kerrosala_m2"]  = df.get("keskim_kerrosala_m2", None)

    for col in ["oilheat_lkm", "sahkolammitys_lkm", "kaukolampo_lkm",
                "maalampo_lkm", "puulammitys_lkm", "muu_lammitys_lkm"]:
        out[col] = df.get(col, 0)

    out["oljy_osuus_pct"] = df.get("oljy_osuus_pct", None)

    for col in ["et_todistuksia_lkm", "et_peitto_pct", "et_keskim_luokka",
                "et_a_b_osuus_pct", "et_e_g_osuus_pct", "e_luku_keskim"]:
        out[col] = None

    for col in ["transitio_potentiaali", "oljykorvaus_potentiaali",
                "sahko_optimointi_pot", "lp_potentiaali", "aurinkopaneeli_pot",
                "spara_tam_alue"]:
        out[col] = df.get(col, None)

    for col in ["pankkikumppani_arvo", "vakuutus_arvo", "energiayhtio_arvo",
                "esg_raportointi_tarve"]:
        out[col] = df.get(col, None)

    out["jousto_potentiaali_mw"] = df.get("jousto_potentiaali_mw", None)
    out["lahde"]                 = df.get("lahde", "Tilastokeskus")
    out["paivitetty"]            = df.get("paivitetty", TODAY)
    out["luotettavuus_1_5"]      = df.get("luotettavuus_1_5", 3)
    out["huomiot"]               = df.get("huomiot", None)

    return out


def export_csv(df: pd.DataFrame, path: str = OUTPUT_CSV) -> None:
    """Vie CSV UTF-8-sig, puolipiste-erotin (Excel-yhteensopiva)."""
    df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")
    rows = len(df)
    size_kb = os.path.getsize(path) // 1024
    log.info("CSV tallennettu: %s (%d riviä, %d KB)", path, rows, size_kb)


def upload_to_supabase(df: pd.DataFrame) -> None:
    """Muuntaa NaN → None ja kirjoittaa Supabaseen."""
    records = []
    for _, row in df.iterrows():
        rec = {}
        for col in df.columns:
            val = row[col]
            if val is None or (isinstance(val, float) and math.isnan(val)):
                rec[col] = None
            elif isinstance(val, (pd.Timestamp,)):
                rec[col] = str(val.date())
            else:
                rec[col] = val
        records.append(rec)

    log.info("Aloitetaan Supabase-upsert: %d riviä...", len(records))
    supabase_upsert(records)
    log.info("Supabase-upsert valmis.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    log.info("=== Spara Energia – Kiinteistörekisteri ===")
    log.info("Käynnistetty: %s", TODAY)

    # 1. Hae Paavo rakennukset
    log.info("--- Vaihe 1/8: Paavo rakennukset ---")
    buildings_df = fetch_paavo_buildings()
    log.info("Postinumeroalueita: %d", len(buildings_df))
    log.info("Pientaloja yhteensä: %d", buildings_df["pientalot_lkm"].sum())

    # 2. Hae Paavo väestö
    log.info("--- Vaihe 2/8: Paavo väestö ---")
    pop_df = fetch_paavo_population()

    # 3. Hae StatFin rakke – lämmitys
    log.info("--- Vaihe 3/8: StatFin rakke – lämmitystapa ---")
    try:
        heating_df = fetch_rakke_heating()
    except Exception as e:
        log.warning("Lämmitysdata epäonnistui: %s – jatketaan ilman", e)
        heating_df = pd.DataFrame()

    # 4. Hae StatFin rakke – rakennusvuosi
    log.info("--- Vaihe 4/8: StatFin rakke – rakennusvuosi ---")
    try:
        year_df = fetch_rakke_construction_year()
    except Exception as e:
        log.warning("Rakennusvuosidata epäonnistui: %s – jatketaan ilman", e)
        year_df = pd.DataFrame()

    # 5. Hae StatFin rakke – rakennusaine
    log.info("--- Vaihe 5/8: StatFin rakke – rakennusaine ---")
    try:
        material_df = fetch_rakke_material()
    except Exception as e:
        log.warning("Rakennusainedata epäonnistui: %s – jatketaan ilman", e)
        material_df = pd.DataFrame()

    # 6. Laske kunta-aggregaatit
    log.info("--- Vaihe 6/8: Kunta-aggregaatit ---")
    heating_shares  = compute_municipality_heating_shares(heating_df)
    year_shares     = compute_municipality_construction_year_shares(year_df)
    material_shares = compute_municipality_material_shares(material_df)
    kunta_pop       = compute_municipality_population(pop_df)

    # 7. Yhdistä
    log.info("--- Vaihe 7/8: Yhdistäminen ja jakelu ---")
    merged = merge_all(buildings_df, pop_df, heating_shares,
                       year_shares, material_shares, kunta_pop)

    # 8. Johdetut sarakkeet
    log.info("--- Vaihe 8/8: Johdetut sarakkeet ---")
    final = add_calculated_columns(merged)
    out_df = _build_output_df(final)

    log.info("Lopullinen rivimäärä: %d", len(out_df))

    # Tulostus
    export_csv(out_df)
    upload_to_supabase(out_df)

    # Loppuraportti
    log.info("=== LOPPURAPORTTI ===")
    log.info("Postinumeroalueita: %d", len(out_df))
    log.info("Pientaloja yhteensä: %d", out_df["pientalot_lkm"].sum())
    log.info("Öljylämmitteisiä yhteensä: %d", out_df["oilheat_lkm"].sum())
    korkea = (out_df["transitio_potentiaali"] == "KORKEA").sum()
    log.info("KORKEA transitio_potentiaali: %d aluetta", korkea)
    puuttuvat_kunta = out_df["kunta"].isna().sum()
    log.info("Postinumeroalueet ilman kuntaa: %d", puuttuvat_kunta)
    log.info("CSV: %s", OUTPUT_CSV)
    log.info("Supabase: %s/rest/v1/%s", SUPABASE_URL, TABLE_NAME)


if __name__ == "__main__":
    main()
