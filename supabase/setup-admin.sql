-- =============================================================================
-- ETJ+ admin-profiilin alustus
-- Aja Supabase SQL Editorissa: https://supabase.com/dashboard/project/ggkuodyaddngzskpgvlt/sql
-- =============================================================================

-- 1. Aseta spara_admin-rooli patrick@sparaenergia.com -tunnukselle
INSERT INTO public.etj_user_profiles (id, role, display_name)
SELECT
  au.id,
  'spara_admin',
  COALESCE(au.raw_user_meta_data->>'display_name', au.email)
FROM auth.users au
WHERE au.email = 'patrick@sparaenergia.com'
ON CONFLICT (id) DO UPDATE
  SET role         = 'spara_admin',
      updated_at   = now();

-- 2. Salli anon-avaimella kirjoittaa etj_leads ja etj_orders
--    (tilauslomake ja ETJ-testi käyttävät anon-avainta)
ALTER TABLE IF EXISTS etj_leads  ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS etj_orders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon_leads_insert"  ON etj_leads;
DROP POLICY IF EXISTS "anon_leads_read"    ON etj_leads;
DROP POLICY IF EXISTS "anon_orders_insert" ON etj_orders;
DROP POLICY IF EXISTS "anon_orders_read"   ON etj_orders;

CREATE POLICY "anon_leads_insert"  ON etj_leads  FOR INSERT WITH CHECK (true);
CREATE POLICY "anon_leads_read"    ON etj_leads  FOR SELECT USING (true);
CREATE POLICY "anon_orders_insert" ON etj_orders FOR INSERT WITH CHECK (true);
CREATE POLICY "anon_orders_read"   ON etj_orders FOR SELECT USING (true);

-- 3. Vahvista: näkyykö profiili?
SELECT id, role, display_name, created_at
FROM public.etj_user_profiles
ORDER BY created_at DESC
LIMIT 10;
