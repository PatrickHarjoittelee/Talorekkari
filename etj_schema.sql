-- =============================================================================
-- Spara ETJ+ Light – Supabase-skeema
-- Energiatehokkuuslaki 2026: velvoitteet 2 700 MWh ja 23 600 MWh rajoilla
-- =============================================================================

-- 1. Yritykset ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etj_companies (
  id                    uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  name                  text    NOT NULL,
  y_tunnus              text    UNIQUE,
  sector                text,
  address               text,
  city                  text,
  contact_name          text,
  contact_email         text,
  etj_agreement_active  boolean DEFAULT false,
  etj_agreement_date    date,
  notes                 text,
  created_at            timestamptz DEFAULT now(),
  updated_at            timestamptz DEFAULT now()
);

-- 2. Kuukausittaiset kulutuslukemat -------------------------------------------
CREATE TABLE IF NOT EXISTS etj_energy_readings (
  id             uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id     uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  year           integer NOT NULL,
  month          integer NOT NULL CHECK (month BETWEEN 1 AND 12),
  electricity_mwh  numeric(10,2) DEFAULT 0,
  heat_mwh         numeric(10,2) DEFAULT 0,
  gas_mwh          numeric(10,2) DEFAULT 0,
  oil_mwh          numeric(10,2) DEFAULT 0,
  other_mwh        numeric(10,2) DEFAULT 0,
  source         text    DEFAULT 'manual',
  notes          text,
  created_at     timestamptz DEFAULT now(),
  UNIQUE (company_id, year, month)
);

CREATE OR REPLACE VIEW v_etj_readings_with_total AS
SELECT *,
  COALESCE(electricity_mwh,0) + COALESCE(heat_mwh,0) + COALESCE(gas_mwh,0)
    + COALESCE(oil_mwh,0) + COALESCE(other_mwh,0) AS total_mwh
FROM etj_energy_readings;

-- 3. Vuosittaiset yhteenvedot -------------------------------------------------
CREATE TABLE IF NOT EXISTS etj_annual_consumption (
  id               uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id       uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  year             integer NOT NULL,
  total_mwh        numeric(10,2),
  electricity_mwh  numeric(10,2),
  heat_mwh         numeric(10,2),
  gas_mwh          numeric(10,2),
  oil_mwh          numeric(10,2),
  floor_area_m2    numeric(10,2),
  employees        integer,
  revenue_meur     numeric(10,3),
  notes            text,
  created_at       timestamptz DEFAULT now(),
  updated_at       timestamptz DEFAULT now(),
  UNIQUE (company_id, year)
);

-- 4. Vaatimustenmukaisuus -----------------------------------------------------
CREATE TABLE IF NOT EXISTS etj_compliance (
  id                          uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id                  uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  checked_at                  timestamptz DEFAULT now(),
  avg_3yr_mwh                 numeric(10,2),
  exceeds_2700                boolean DEFAULT false,
  exceeds_23600               boolean DEFAULT false,
  audit_required              boolean DEFAULT false,
  audit_due_date              date,
  last_audit_date             date,
  ems_required                boolean DEFAULT false,
  ems_due_date                date,
  etj_exemption_active        boolean DEFAULT false,
  energiavirasto_reported     boolean DEFAULT false,
  energiavirasto_report_date  date,
  -- compliant / pending / non_compliant / exempt
  compliance_status           text    DEFAULT 'unknown',
  notes                       text
);

-- 5. Energiatavoitteet --------------------------------------------------------
CREATE TABLE IF NOT EXISTS etj_targets (
  id                    uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id            uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  year                  integer NOT NULL,
  baseline_year         integer,
  baseline_mwh          numeric(10,2),
  target_mwh            numeric(10,2),
  target_reduction_pct  numeric(5,2),
  actual_mwh            numeric(10,2),
  -- pending / on_track / achieved / missed
  status                text    DEFAULT 'pending',
  notes                 text,
  created_at            timestamptz DEFAULT now(),
  UNIQUE (company_id, year)
);

-- 6. Toimenpidelista ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS etj_actions (
  id                     uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id             uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  title                  text    NOT NULL,
  description            text,
  -- valaistus / lviv / prosessit / kuori / uusiutuva / kayttaytyminen
  category               text,
  -- high / medium / low
  priority               text    DEFAULT 'medium',
  estimated_savings_mwh  numeric(10,2),
  estimated_savings_eur  numeric(12,2),
  investment_eur         numeric(12,2),
  payback_years          numeric(5,1),
  -- open / in_progress / completed / rejected
  status                 text    DEFAULT 'open',
  responsible_person     text,
  due_date               date,
  completed_date         date,
  actual_savings_mwh     numeric(10,2),
  actual_savings_eur     numeric(12,2),
  created_at             timestamptz DEFAULT now(),
  updated_at             timestamptz DEFAULT now()
);

-- 7. Hälytykset ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS etj_alerts (
  id               uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id       uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  -- kulutus_piikki / tavoite_poikkeama / raportti_erapaiva / katselmus_erapaiva / raja_ylitetty
  alert_type       text    NOT NULL,
  -- info / warning / critical
  severity         text    DEFAULT 'info',
  title            text    NOT NULL,
  message          text,
  triggered_at     timestamptz DEFAULT now(),
  acknowledged_at  timestamptz,
  acknowledged_by  text,
  is_active        boolean DEFAULT true
);

-- 8. Energiaviraston vuosiraportit --------------------------------------------
CREATE TABLE IF NOT EXISTS etj_energiavirasto_reports (
  id                   uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id           uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  reporting_year       integer NOT NULL,
  total_mwh            numeric(10,2),
  -- none / 2700 / 23600
  threshold_crossed    text,
  submission_deadline  date,
  -- draft / ready / submitted / confirmed
  submission_status    text DEFAULT 'draft',
  submitted_at         timestamptz,
  submitted_by         text,
  report_data          jsonb,
  created_at           timestamptz DEFAULT now(),
  updated_at           timestamptz DEFAULT now(),
  UNIQUE (company_id, reporting_year)
);

-- =============================================================================
-- Views
-- =============================================================================

CREATE OR REPLACE VIEW v_etj_compliance_overview AS
SELECT
  c.id,
  c.name,
  c.y_tunnus,
  c.sector,
  c.city,
  c.etj_agreement_active,
  comp.avg_3yr_mwh,
  comp.exceeds_2700,
  comp.exceeds_23600,
  comp.audit_required,
  comp.audit_due_date,
  comp.ems_required,
  comp.ems_due_date,
  comp.etj_exemption_active,
  comp.compliance_status,
  comp.energiavirasto_reported,
  comp.checked_at
FROM etj_companies c
LEFT JOIN LATERAL (
  SELECT * FROM etj_compliance
  WHERE company_id = c.id
  ORDER BY checked_at DESC
  LIMIT 1
) comp ON true;

CREATE OR REPLACE VIEW v_etj_annual_summary AS
SELECT
  a.company_id,
  c.name AS company_name,
  a.year,
  a.total_mwh,
  a.floor_area_m2,
  a.employees,
  CASE WHEN a.floor_area_m2 > 0 THEN round(a.total_mwh * 1000 / a.floor_area_m2, 1) ELSE NULL END AS kwh_per_m2,
  CASE WHEN a.employees   > 0 THEN round(a.total_mwh * 1000 / a.employees, 0) ELSE NULL END AS kwh_per_employee,
  t.target_mwh,
  t.target_reduction_pct,
  CASE
    WHEN t.baseline_mwh > 0 AND a.total_mwh IS NOT NULL
    THEN round((a.total_mwh - t.baseline_mwh) / t.baseline_mwh * 100, 1)
    ELSE NULL
  END AS change_vs_baseline_pct
FROM etj_annual_consumption a
JOIN etj_companies c ON c.id = a.company_id
LEFT JOIN etj_targets t ON t.company_id = a.company_id AND t.year = a.year;

-- =============================================================================
-- Row Level Security (mukauta tenant-logiikalla tarpeen mukaan)
-- =============================================================================

ALTER TABLE etj_companies              ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_energy_readings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_annual_consumption     ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_compliance             ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_targets                ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_actions                ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_alerts                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_energiavirasto_reports ENABLE ROW LEVEL SECURITY;

-- Lukuoikeus kaikille anon-avaimella
CREATE POLICY "anon_read"  ON etj_companies              FOR SELECT USING (true);
CREATE POLICY "anon_read"  ON etj_energy_readings        FOR SELECT USING (true);
CREATE POLICY "anon_read"  ON etj_annual_consumption     FOR SELECT USING (true);
CREATE POLICY "anon_read"  ON etj_compliance             FOR SELECT USING (true);
CREATE POLICY "anon_read"  ON etj_targets                FOR SELECT USING (true);
CREATE POLICY "anon_read"  ON etj_actions                FOR SELECT USING (true);
CREATE POLICY "anon_read"  ON etj_alerts                 FOR SELECT USING (true);
CREATE POLICY "anon_read"  ON etj_energiavirasto_reports FOR SELECT USING (true);

-- Kirjoitusoikeus kuukausittaisille kulutustiedoille (dashboard-syöttölomake käyttää anon-avainta).
-- Tuotannossa rajaa authenticated-rooliin tai reititä service-key-funktion kautta.
CREATE POLICY "anon_insert" ON etj_energy_readings FOR INSERT WITH CHECK (true);
CREATE POLICY "anon_update" ON etj_energy_readings FOR UPDATE USING (true);
CREATE POLICY "anon_insert" ON etj_annual_consumption FOR INSERT WITH CHECK (true);
CREATE POLICY "anon_update" ON etj_annual_consumption FOR UPDATE USING (true);
