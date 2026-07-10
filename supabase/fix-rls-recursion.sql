-- =============================================================================
-- Korjaus: infinite recursion etj_user_profiles -taulussa
-- Aja Supabase SQL Editorissa: https://supabase.com/dashboard/project/ggkuodyaddngzskpgvlt/sql
-- =============================================================================

-- SECURITY DEFINER -funktio tarkistaa admin-roolin ilman RLS:ää.
-- Tämä katkaisee rekursion: funktio ajaa function-ownerin oikeuksilla
-- eikä laukaise etj_user_profiles-policya uudelleen.
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

-- Korjataan etj_user_profiles -policyt (ne aiheuttivat rekursion)
DROP POLICY IF EXISTS "own_profile_select" ON etj_user_profiles;
DROP POLICY IF EXISTS "admin_profile_all"  ON etj_user_profiles;
DROP POLICY IF EXISTS "own_profile_insert" ON etj_user_profiles;
DROP POLICY IF EXISTS "own_profile_update" ON etj_user_profiles;

-- Käyttäjä lukee oman rivin; admin lukee kaikki (ilman rekursiota)
CREATE POLICY "own_profile_select" ON etj_user_profiles
  FOR SELECT USING (id = auth.uid() OR etj_is_admin());

-- Käyttäjä päivittää oman rivin (profiilin muokkaus, puh.nro jne.)
CREATE POLICY "own_profile_update" ON etj_user_profiles
  FOR UPDATE USING (id = auth.uid() OR etj_is_admin())
  WITH CHECK (
    id = auth.uid()
    -- Roolia voi vaihtaa vain admin
    AND (role = (SELECT role FROM etj_user_profiles WHERE id = auth.uid()) OR etj_is_admin())
    OR etj_is_admin()
  );

-- Admin luo/poistaa profiileja
CREATE POLICY "admin_profile_insert" ON etj_user_profiles
  FOR INSERT WITH CHECK (etj_is_admin() OR id = auth.uid());

CREATE POLICY "admin_profile_delete" ON etj_user_profiles
  FOR DELETE USING (etj_is_admin());

-- etj_user_company_access: korjataan myös tämän policyt (ne viittasivat suoraan etj_user_profiles:iin)
DROP POLICY IF EXISTS "own_access_select"  ON etj_user_company_access;
DROP POLICY IF EXISTS "admin_access_write" ON etj_user_company_access;

CREATE POLICY "own_access_select" ON etj_user_company_access
  FOR SELECT USING (user_id = auth.uid() OR etj_is_admin());

CREATE POLICY "admin_access_write" ON etj_user_company_access
  FOR ALL USING (etj_is_admin());

-- Tarkista että etj_can_access_company() on yhä SECURITY DEFINER
-- (se on jo OK jos et ole muokannut sitä, mutta ajetaan varmuudeksi)
CREATE OR REPLACE FUNCTION etj_can_access_company(cid uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    etj_is_admin()
    OR EXISTS (
      SELECT 1 FROM etj_user_profiles p
      JOIN etj_companies c ON lower(c.city) = lower(p.municipality)
      WHERE p.id = auth.uid() AND p.role = 'municipality' AND c.id = cid
    )
    OR EXISTS (
      SELECT 1 FROM etj_user_company_access
      WHERE user_id = auth.uid() AND company_id = cid
    )
    OR EXISTS (
      SELECT 1 FROM etj_company_hierarchy h
      JOIN etj_user_company_access a ON a.company_id = h.parent_id
      WHERE a.user_id = auth.uid() AND h.child_id = cid
    );
$$;

-- Vahvista: kirjaudu ulos ja sisään ETJ+:aan — virhe pitäisi kadota.
-- Tarkistus: pitäisi palauttaa oma rivi ilman virhettä:
SELECT id, role, display_name FROM public.etj_user_profiles WHERE id = auth.uid();
