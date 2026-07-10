-- =============================================================================
-- Spara ETJ+ Light – Auth & Hierarchy -skeema
-- Lisää etj_schema.sql:n päälle (aja tämän jälkeen)
-- =============================================================================

-- 1. Käyttäjäprofiilit --------------------------------------------------------
CREATE TABLE IF NOT EXISTS etj_user_profiles (
  id             uuid    PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  -- spara_admin / municipality / customer
  role           text    NOT NULL CHECK (role IN ('spara_admin','municipality','customer')),
  municipality   text,   -- vain municipality-roolia varten
  display_name   text,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

-- 2. Konsernirakenne (parent → child) -----------------------------------------
CREATE TABLE IF NOT EXISTS etj_company_hierarchy (
  parent_id         uuid NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  child_id          uuid NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  -- subsidiary / branch / site
  relationship_type text DEFAULT 'subsidiary',
  PRIMARY KEY (parent_id, child_id)
);

-- 3. Käyttäjä ↔ Yritys -oikeudet (customer-rooli) ----------------------------
CREATE TABLE IF NOT EXISTS etj_user_company_access (
  user_id      uuid NOT NULL REFERENCES auth.users(id)    ON DELETE CASCADE,
  company_id   uuid NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  -- read / write / admin
  access_level text DEFAULT 'read',
  PRIMARY KEY (user_id, company_id)
);

-- 4. Käyttöpaikat (Spara-äppi kytkeytyy tänne) --------------------------------
CREATE TABLE IF NOT EXISTS etj_sites (
  id                    uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id            uuid    NOT NULL REFERENCES etj_companies(id) ON DELETE CASCADE,
  name                  text    NOT NULL,
  address               text,
  city                  text,
  -- Spara-äpin käyttöpaikan tunniste (FI-metering point ID tai sisäinen)
  spara_usage_point_id  text    UNIQUE,
  floor_area_m2         numeric(10,2),
  -- office / warehouse / production / retail / other
  site_type             text,
  active                boolean DEFAULT true,
  created_at            timestamptz DEFAULT now(),
  updated_at            timestamptz DEFAULT now()
);

-- =============================================================================
-- RLS uusille tauluille
-- =============================================================================
ALTER TABLE etj_user_profiles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_company_hierarchy   ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_user_company_access ENABLE ROW LEVEL SECURITY;
ALTER TABLE etj_sites               ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Apufunktio: voiko kirjautunut käyttäjä nähdä yrityksen cid?
-- Security Definer → funktio näkee kaiken vaikka kutsuva context ei saisi
-- =============================================================================
-- Apufunktio admin-tarkistukseen — SECURITY DEFINER katkaisee
-- etj_user_profiles-rekursion kun sitä käytetään saman taulun policyssa.
CREATE OR REPLACE FUNCTION etj_is_admin()
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM etj_user_profiles
    WHERE id = auth.uid() AND role = 'spara_admin'
  );
$$;

CREATE OR REPLACE FUNCTION etj_can_access_company(cid uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    etj_is_admin()
    OR
    -- Kunta näkee kaupunkiinsa sidotut yritykset
    EXISTS (
      SELECT 1 FROM etj_user_profiles p
      JOIN etj_companies c ON lower(c.city) = lower(p.municipality)
      WHERE p.id = auth.uid() AND p.role = 'municipality' AND c.id = cid
    )
    OR
    -- Asiakas: suora oikeus
    EXISTS (
      SELECT 1 FROM etj_user_company_access
      WHERE user_id = auth.uid() AND company_id = cid
    )
    OR
    -- Asiakas: tytäryhtiöoikeus hierarkian kautta
    EXISTS (
      SELECT 1 FROM etj_company_hierarchy h
      JOIN etj_user_company_access a ON a.company_id = h.parent_id
      WHERE a.user_id = auth.uid() AND h.child_id = cid
    );
$$;

-- =============================================================================
-- Päivitetyt RLS-policyt etj_schema.sql-tauluille
-- (korvaa vanhat anon_read-policyt)
-- =============================================================================

-- etj_companies
DROP POLICY IF EXISTS "anon_read" ON etj_companies;
CREATE POLICY "role_company_select" ON etj_companies
  FOR SELECT USING (etj_can_access_company(id));
CREATE POLICY "admin_company_all" ON etj_companies
  FOR ALL USING (
    EXISTS (SELECT 1 FROM etj_user_profiles WHERE id = auth.uid() AND role = 'spara_admin')
  );

-- etj_energy_readings
DROP POLICY IF EXISTS "anon_read"   ON etj_energy_readings;
DROP POLICY IF EXISTS "anon_insert" ON etj_energy_readings;
DROP POLICY IF EXISTS "anon_update" ON etj_energy_readings;
CREATE POLICY "role_readings_select" ON etj_energy_readings
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "role_readings_write" ON etj_energy_readings
  FOR ALL USING (etj_can_access_company(company_id));

-- etj_annual_consumption
DROP POLICY IF EXISTS "anon_read"   ON etj_annual_consumption;
DROP POLICY IF EXISTS "anon_insert" ON etj_annual_consumption;
DROP POLICY IF EXISTS "anon_update" ON etj_annual_consumption;
CREATE POLICY "role_annual_select" ON etj_annual_consumption
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "role_annual_write" ON etj_annual_consumption
  FOR ALL USING (etj_can_access_company(company_id));

-- etj_compliance
DROP POLICY IF EXISTS "anon_read" ON etj_compliance;
CREATE POLICY "role_compliance_select" ON etj_compliance
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "admin_compliance_write" ON etj_compliance
  FOR ALL USING (
    EXISTS (SELECT 1 FROM etj_user_profiles WHERE id = auth.uid() AND role = 'spara_admin')
  );

-- etj_targets
DROP POLICY IF EXISTS "anon_read" ON etj_targets;
CREATE POLICY "role_targets_select" ON etj_targets
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "role_targets_write" ON etj_targets
  FOR ALL USING (etj_can_access_company(company_id));

-- etj_actions
DROP POLICY IF EXISTS "anon_read" ON etj_actions;
CREATE POLICY "role_actions_select" ON etj_actions
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "role_actions_write" ON etj_actions
  FOR ALL USING (etj_can_access_company(company_id));

-- etj_alerts
DROP POLICY IF EXISTS "anon_read" ON etj_alerts;
CREATE POLICY "role_alerts_select" ON etj_alerts
  FOR SELECT USING (etj_can_access_company(company_id));

-- etj_energiavirasto_reports
DROP POLICY IF EXISTS "anon_read" ON etj_energiavirasto_reports;
CREATE POLICY "role_reports_select" ON etj_energiavirasto_reports
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "role_reports_write" ON etj_energiavirasto_reports
  FOR ALL USING (etj_can_access_company(company_id));

-- etj_sites
CREATE POLICY "role_sites_select" ON etj_sites
  FOR SELECT USING (etj_can_access_company(company_id));
CREATE POLICY "admin_sites_write" ON etj_sites
  FOR ALL USING (
    EXISTS (SELECT 1 FROM etj_user_profiles WHERE id = auth.uid() AND role = 'spara_admin')
    OR etj_can_access_company(company_id)
  );

-- etj_company_hierarchy
CREATE POLICY "role_hierarchy_select" ON etj_company_hierarchy
  FOR SELECT USING (
    etj_can_access_company(parent_id) OR etj_can_access_company(child_id)
  );
CREATE POLICY "admin_hierarchy_write" ON etj_company_hierarchy
  FOR ALL USING (
    EXISTS (SELECT 1 FROM etj_user_profiles WHERE id = auth.uid() AND role = 'spara_admin')
  );

-- etj_user_company_access (admin hallinnoi, käyttäjä lukee omansa)
CREATE POLICY "own_access_select" ON etj_user_company_access
  FOR SELECT USING (user_id = auth.uid() OR etj_is_admin());
CREATE POLICY "admin_access_write" ON etj_user_company_access
  FOR ALL USING (etj_is_admin());

-- etj_user_profiles — käyttää etj_is_admin() rekursion välttämiseksi
CREATE POLICY "own_profile_select" ON etj_user_profiles
  FOR SELECT USING (id = auth.uid() OR etj_is_admin());
CREATE POLICY "own_profile_update" ON etj_user_profiles
  FOR UPDATE USING (id = auth.uid() OR etj_is_admin())
  WITH CHECK (id = auth.uid() OR etj_is_admin());
CREATE POLICY "admin_profile_insert" ON etj_user_profiles
  FOR INSERT WITH CHECK (etj_is_admin() OR id = auth.uid());
CREATE POLICY "admin_profile_delete" ON etj_user_profiles
  FOR DELETE USING (etj_is_admin());

-- =============================================================================
-- View: yritysrakenne hierarkialla
-- =============================================================================
CREATE OR REPLACE VIEW v_etj_company_tree AS
SELECT
  c.id,
  c.name,
  c.y_tunnus,
  c.sector,
  c.city,
  c.etj_agreement_active,
  h.parent_id,
  p.name AS parent_name,
  (SELECT count(*) FROM etj_company_hierarchy WHERE parent_id = c.id) AS child_count,
  (SELECT count(*) FROM etj_sites WHERE company_id = c.id AND active = true) AS site_count
FROM etj_companies c
LEFT JOIN etj_company_hierarchy h ON h.child_id = c.id
LEFT JOIN etj_companies p ON p.id = h.parent_id;

-- =============================================================================
-- Trigger: päivitä updated_at automaattisesti
-- =============================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

CREATE OR REPLACE TRIGGER trg_etj_companies_updated
  BEFORE UPDATE ON etj_companies
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER trg_etj_sites_updated
  BEFORE UPDATE ON etj_sites
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
