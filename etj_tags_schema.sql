-- =============================================================================
-- Spara ETJ+ – Energiatägit
-- Aja etj_auth_schema.sql:n jälkeen
-- =============================================================================

-- 1. Tägit (yrityskohtaiset energian käyttökohde-/prosessileimaukset) ----------
CREATE TABLE IF NOT EXISTS etj_energy_tags (
  id          uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  name        text    NOT NULL,
  color       text    DEFAULT '#4CAF50',
  description text,
  created_at  timestamptz DEFAULT now(),
  UNIQUE (company_id, name)
);

-- 2. Tägitetyt energiamäärät (kuukausittain, energialähteittäin) ---------------
--    Useita rivejä per (company, year, month, energy_type) – yksi per tägi.
--    Ei tarvitse summata kokonaiskulutukseen: osatägitys on sallittu.
CREATE TABLE IF NOT EXISTS etj_energy_tag_allocations (
  id          uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  year        integer NOT NULL,
  month       integer NOT NULL CHECK (month BETWEEN 1 AND 12),
  energy_type text    NOT NULL CHECK (energy_type IN ('electricity','heat','gas','oil','other')),
  amount_mwh  numeric(10,2) NOT NULL CHECK (amount_mwh >= 0),
  tag_id      uuid    NOT NULL REFERENCES etj_energy_tags(id) ON DELETE CASCADE,
  notes       text,
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

ALTER TABLE etj_energy_tags            ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_energy_tag_allocations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "role_tags_select" ON etj_energy_tags
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "role_tags_write" ON etj_energy_tags
  FOR ALL USING (etj_can_access_company(company_id));

CREATE POLICY "role_tag_alloc_select" ON etj_energy_tag_allocations
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "role_tag_alloc_write" ON etj_energy_tag_allocations
  FOR ALL USING (etj_can_access_company(company_id));

-- =============================================================================
-- View: kuukausitason tägikooste (käytetään raportoinnissa)
-- =============================================================================
CREATE OR REPLACE VIEW v_etj_tag_monthly AS
SELECT
  a.company_id,
  c.name         AS company_name,
  t.id           AS tag_id,
  t.name         AS tag_name,
  t.color        AS tag_color,
  a.energy_type,
  a.year,
  a.month,
  SUM(a.amount_mwh) AS amount_mwh
FROM etj_energy_tag_allocations a
JOIN etj_companies  c ON c.id = a.company_id
JOIN etj_energy_tags t ON t.id = a.tag_id
GROUP BY a.company_id, c.name, t.id, t.name, t.color, a.energy_type, a.year, a.month;

-- View: vuositason tägikooste
CREATE OR REPLACE VIEW v_etj_tag_annual AS
SELECT
  a.company_id,
  c.name         AS company_name,
  t.id           AS tag_id,
  t.name         AS tag_name,
  t.color        AS tag_color,
  a.energy_type,
  a.year,
  SUM(a.amount_mwh)         AS total_mwh,
  COUNT(DISTINCT a.month)   AS months_reported
FROM etj_energy_tag_allocations a
JOIN etj_companies  c ON c.id = a.company_id
JOIN etj_energy_tags t ON t.id = a.tag_id
GROUP BY a.company_id, c.name, t.id, t.name, t.color, a.energy_type, a.year;

-- =============================================================================
-- Trigger: updated_at
-- =============================================================================
CREATE OR REPLACE TRIGGER trg_etj_tag_alloc_updated
  BEFORE UPDATE ON etj_energy_tag_allocations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
