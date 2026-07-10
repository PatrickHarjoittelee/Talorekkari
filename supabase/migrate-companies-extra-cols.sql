-- =============================================================================
-- Migraatio: lisää puuttuvat sarakkeet etj_companies-tauluun
-- Aja Supabase SQL Editorissa: https://supabase.com/dashboard/project/ggkuodyaddngzskpgvlt/sql
-- =============================================================================

ALTER TABLE etj_companies
  ADD COLUMN IF NOT EXISTS post_code         text,
  ADD COLUMN IF NOT EXISTS company_form      text,
  ADD COLUMN IF NOT EXISTS registration_date date;

-- Vahvistus
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'etj_companies'
ORDER BY ordinal_position;
