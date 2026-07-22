-- =============================================================================
-- Spara Energia – CRM Prospektit (B2B)
-- Kampanjat: ETJ+ | Talopakettivalmistajat FIN | Talopakettivalmistajat SWE
-- =============================================================================

CREATE TABLE IF NOT EXISTS crm_prospects (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Tunnisteet
  spara_id            text        UNIQUE,       -- ID20260000, TALOFIN001 …
  kampanja            text,                     -- ETJ+ | Talopakettivalmistajat FIN | SWE
  prioriteetti        text,                     -- A / B  tai  1–40
  sija                integer,                  -- numeerinen järjestysnumero

  -- Yritysprofiili
  segmentti           text,                     -- Hotelli, Kauppakeskus, Puu, Hirsi …
  yritys_nimi         text        NOT NULL,
  juridinen_yhtio     text,
  osoite              text,
  kaupunki            text,
  y_tunnus            text,
  liikevaihto_meur    text,
  kulutusarvio_mwh    text,       -- MWh/v arvio (ETJ+)
  pisteet             numeric,    -- pisteytys 0–100 tai tähdet 1–10

  -- Yhteystiedot (yritys)
  vaihde_puhelin      text,
  yleinen_sahkoposti  text,
  www                 text,

  -- Myyntisignaalit
  signaali            text,
  perustelu           text,       -- päätöstaso / perustelu
  velvoiteluokka      text,       -- ETJ-velvoiteluokka / rajaus
  huomiot             text,       -- varoitukset

  -- Yhteyshenkilö
  yhteyshenkilö       text,
  titteli             text,
  suora_numero        text,
  henk_sahkoposti     text,
  linkedin            text,

  -- Sheets-tila (alkuperäinen)
  kontaktoinnin_tila  text,
  tulos_seuraava_toimi text,
  lahde               text,

  -- CRM-suppilo (oma hallinta)
  vaihe               text        NOT NULL DEFAULT 'Uusi',
  -- Uusi | Yhteytetty | Tapaaminen | Tarjous | Sopimus | Hylätty

  omistaja            text,
  seuraava_toimenpide text,
  seuraava_pvm        date,
  muistiinpanot       text,

  created_at          timestamptz DEFAULT now(),
  updated_at          timestamptz DEFAULT now()
);

-- Aktiviteettihistoria
CREATE TABLE IF NOT EXISTS crm_activities (
  id           uuid  PRIMARY KEY DEFAULT gen_random_uuid(),
  prospect_id  uuid  NOT NULL REFERENCES crm_prospects(id) ON DELETE CASCADE,
  tyyppi       text  NOT NULL DEFAULT 'kommentti',
  teksti       text  NOT NULL,
  tekija       text,
  created_at   timestamptz DEFAULT now()
);

-- Trigger: updated_at
CREATE OR REPLACE FUNCTION crm_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;
DROP TRIGGER IF EXISTS crm_prospects_upd ON crm_prospects;
CREATE TRIGGER crm_prospects_upd
  BEFORE UPDATE ON crm_prospects
  FOR EACH ROW EXECUTE FUNCTION crm_set_updated_at();

-- RLS
ALTER TABLE crm_prospects   ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_activities  ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS crm_p_read  ON crm_prospects;
DROP POLICY IF EXISTS crm_p_write ON crm_prospects;
DROP POLICY IF EXISTS crm_a_read  ON crm_activities;
DROP POLICY IF EXISTS crm_a_write ON crm_activities;
CREATE POLICY crm_p_read  ON crm_prospects  FOR SELECT USING (true);
CREATE POLICY crm_p_write ON crm_prospects  FOR ALL    USING (true) WITH CHECK (true);
CREATE POLICY crm_a_read  ON crm_activities FOR SELECT USING (true);
CREATE POLICY crm_a_write ON crm_activities FOR ALL    USING (true) WITH CHECK (true);

-- Indeksit
CREATE INDEX IF NOT EXISTS idx_crm_vaihe    ON crm_prospects(vaihe);
CREATE INDEX IF NOT EXISTS idx_crm_kampanja ON crm_prospects(kampanja);
CREATE INDEX IF NOT EXISTS idx_crm_kaupunki ON crm_prospects(kaupunki);
CREATE INDEX IF NOT EXISTS idx_crm_pisteet  ON crm_prospects(pisteet);
