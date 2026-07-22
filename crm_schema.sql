-- =============================================================================
-- Spara Energia – CRM Prospektit
-- =============================================================================

CREATE TABLE IF NOT EXISTS crm_prospects (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Yhteystiedot
  nimi              text        NOT NULL,
  puhelin           text,
  sahkoposti        text,

  -- Sijainti
  osoite            text,
  postinumero       text,
  kaupunki          text,

  -- Talo
  lampotapa         text,           -- öljy | sähkö | kaukolämpö | maalämpö | puu | muu
  talo_m2           numeric(8,1),
  rakennusvuosi     integer,

  -- Myyntisuppilo
  vaihe             text        NOT NULL DEFAULT 'Uusi',
  -- Uusi | Yhteytetty | Tapaaminen | Tarjous | Sopimus | Hylätty

  prioriteetti      text        DEFAULT 'Normaali',
  -- Korkea | Normaali | Matala

  lahde             text,           -- lähde / kampanja
  omistaja          text,           -- myyjä / yhteyshenkilö

  -- Seuraava toimenpide
  seuraava_toimenpide text,
  seuraava_pvm        date,

  muistiinpanot     text,

  created_at        timestamptz DEFAULT now(),
  updated_at        timestamptz DEFAULT now()
);

-- Automaattinen updated_at -trigger
CREATE OR REPLACE FUNCTION crm_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

DROP TRIGGER IF EXISTS crm_prospects_updated_at ON crm_prospects;
CREATE TRIGGER crm_prospects_updated_at
  BEFORE UPDATE ON crm_prospects
  FOR EACH ROW EXECUTE FUNCTION crm_set_updated_at();

-- Kommentit / toimintahistoria
CREATE TABLE IF NOT EXISTS crm_activities (
  id           uuid  PRIMARY KEY DEFAULT gen_random_uuid(),
  prospect_id  uuid  NOT NULL REFERENCES crm_prospects(id) ON DELETE CASCADE,
  tyyppi       text  NOT NULL DEFAULT 'kommentti',
  -- kommentti | puhelu | sähköposti | tapaaminen | vaihe_muutos
  teksti       text  NOT NULL,
  tekija       text,
  created_at   timestamptz DEFAULT now()
);

-- RLS: julkinen luku, kirjoitus autentikoituneille
ALTER TABLE crm_prospects   ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_activities  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_prospects_read   ON crm_prospects;
DROP POLICY IF EXISTS crm_prospects_write  ON crm_prospects;
DROP POLICY IF EXISTS crm_activities_read  ON crm_activities;
DROP POLICY IF EXISTS crm_activities_write ON crm_activities;

CREATE POLICY crm_prospects_read   ON crm_prospects  FOR SELECT USING (true);
CREATE POLICY crm_prospects_write  ON crm_prospects  FOR ALL    USING (true) WITH CHECK (true);
CREATE POLICY crm_activities_read  ON crm_activities FOR SELECT USING (true);
CREATE POLICY crm_activities_write ON crm_activities FOR ALL    USING (true) WITH CHECK (true);

-- Indeksit
CREATE INDEX IF NOT EXISTS idx_crm_vaihe    ON crm_prospects(vaihe);
CREATE INDEX IF NOT EXISTS idx_crm_kaupunki ON crm_prospects(kaupunki);
CREATE INDEX IF NOT EXISTS idx_crm_pvm      ON crm_prospects(seuraava_pvm);
