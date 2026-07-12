# Spara ETJ+ — Versiohistoria

## Versioformaatti

```
YYMMMNNN
│  │  └── Juokseva numero kuukauden sisällä (01, 02, 03 …)
│  └───── Kuukausikoodi — suomenkielisen kuunimen 3 ensimmäistä kirjainta
└──────── Vuosi (2 numeroa)
```

| Kuukausi | Koodi | Kuukausi  | Koodi |
|----------|-------|-----------|-------|
| Tammikuu | TAM   | Heinäkuu  | HEI   |
| Helmikuu | HEL   | Elokuu    | ELO   |
| Maaliskuu| MAA   | Syyskuu   | SYY   |
| Huhtikuu | HUH   | Lokakuu   | LOK   |
| Toukokuu | TOU   | Marraskuu | MAR   |
| Kesäkuu  | KES   | Joulukuu  | JOU   |

Esimerkki: `26HEI01` = heinäkuu 2026, ensimmäinen julkaisu

---

## 26HEI01 — Heinäkuu 2026

### Softa — `dashboard/etj-plus.html`
- Aktivointipolku sähköpostikutsulla (ETJ-testi → tilaussopimus → Supabase invite → kirjautuminen)
- ETJ-koodin haku anon key -REST-haulla (RLS-ohitus)
- Mobiiliburger-valikko kaikilla välilehdillä
- Ohjatun tuonnin nav-painikkeet toimivat (sticky, 3-palsta)
- Uloskirjautuminen toimii kaikilla välilehdillä
- Oikea Spara-logo kirjautumissivulle
- Footer-linkit palvelukuvaukseen, käyttöohjeeseen ja tilaussopimukseen

### Palvelukuvaus — `dashboard/etj-palvelukuvaus.html`
- Julkaistu: hero, kenelle, velvoiteaikajana, 6 palveluominaisuutta, miten alkuun
- Mobiiliburger-valikko

### Käyttöohje — `dashboard/etj-kayttohje.html`
- Julkaistu: kaikki välilehdet dokumentoitu, roolit, integraatiot, UKK
- Kirjautuminen-osio: todellinen aktivointipolku (ei väliaikaista salasanaa)
- UKK: sopimusperusteinen kysymyssarja — 12 kk sitoumus, irtisanominen, maksuehto,
  GDPR-roolit, 99 % SLA, vastuunrajoitus, sovellettava laki
- Mobiiliburger-valikko

### Tilaussopimus — `dashboard/etj-tilaussopimus.html`
- Julkaistu: §1–§12, allekirjoitussivu, Liite A (palvelun sisältö), Liite B (DPA/GDPR)
- Korvaa aiemman `v1.0`-merkinnän
- Mobiiliburger-valikko; mobiilinäkymän overflow-ongelma korjattu
