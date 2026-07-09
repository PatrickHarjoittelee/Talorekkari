// Supabase Edge Function: bind-etj-user
// Deploy: supabase functions deploy bind-etj-user --project-ref ggkuodyaddngzskpgvlt
//
// Called from etj-onboarding.html after the user enters their ETJ code.
// Requires: valid user JWT in Authorization header.
// Creates etj_companies (if missing) and etj_user_company_access rows.

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS })

  try {
    const { etj_code } = await req.json() as { etj_code: string }
    const code = (etj_code || '').toUpperCase().trim()
    if (!code || code.length < 4) throw new Error('Virheellinen koodi')

    const supaUrl  = Deno.env.get('SUPABASE_URL')!
    const svcKey   = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    const anonKey  = Deno.env.get('SUPABASE_ANON_KEY')!

    // Verify caller has a valid user session
    const authHeader = req.headers.get('Authorization')
    if (!authHeader) throw new Error('Kirjautuminen puuttuu')

    const userClient = createClient(supaUrl, anonKey, {
      global: { headers: { Authorization: authHeader } },
    })
    const { data: { user }, error: userErr } = await userClient.auth.getUser()
    if (userErr || !user) throw new Error('Tunnistautuminen epäonnistui')

    const admin = createClient(supaUrl, svcKey)

    // ── 1. Lookup the ETJ test lead by code ──────────────────────────────────
    const { data: leads } = await admin
      .from('etj_leads')
      .select('company_name,y_tunnus,city,contact_name,contact_email,sector')
      .eq('lead_code', code)
      .limit(1)

    // ── 2. Fallback: lookup signed order by etj_code ─────────────────────────
    let leadRow = leads?.[0] ?? null
    if (!leadRow) {
      const { data: orders } = await admin
        .from('etj_orders')
        .select('company_name,y_tunnus,city,contact_name,contact_email')
        .eq('etj_code', code)
        .eq('status', 'signed')
        .limit(1)
      leadRow = orders?.[0] ?? null
    }

    if (!leadRow) throw new Error('Koodia ei löydy. Tarkista koodi ja yritä uudelleen.')

    const { company_name, y_tunnus, city, contact_name, contact_email, sector } = leadRow

    // ── 3. Find or create the company ────────────────────────────────────────
    let companyId: string

    if (y_tunnus) {
      const { data: existing } = await admin
        .from('etj_companies')
        .select('id,name')
        .eq('y_tunnus', y_tunnus)
        .limit(1)

      if (existing?.[0]) {
        companyId = existing[0].id
      } else {
        const { data: created, error: cErr } = await admin
          .from('etj_companies')
          .insert({
            name:                company_name,
            y_tunnus:            y_tunnus,
            city:                city || null,
            sector:              sector || null,
            contact_name:        contact_name || null,
            contact_email:       contact_email || null,
            etj_agreement_active: true,
            etj_agreement_date:  new Date().toISOString().split('T')[0],
          })
          .select('id')
          .single()
        if (cErr) throw new Error('Yrityksen luonti epäonnistui: ' + cErr.message)
        companyId = created!.id
      }
    } else {
      // No y_tunnus — create by name
      const { data: created, error: cErr } = await admin
        .from('etj_companies')
        .insert({
          name:                company_name,
          contact_name:        contact_name || null,
          contact_email:       contact_email || null,
          etj_agreement_active: true,
          etj_agreement_date:  new Date().toISOString().split('T')[0],
        })
        .select('id')
        .single()
      if (cErr) throw new Error('Yrityksen luonti epäonnistui: ' + cErr.message)
      companyId = created!.id
    }

    // ── 4. Grant user access to the company ──────────────────────────────────
    const { error: accErr } = await admin
      .from('etj_user_company_access')
      .upsert({ user_id: user.id, company_id: companyId, access_level: 'admin' })
    if (accErr) throw new Error('Käyttöoikeuden luonti epäonnistui: ' + accErr.message)

    return new Response(
      JSON.stringify({ success: true, company_name, company_id: companyId }),
      { status: 200, headers: { ...CORS, 'Content-Type': 'application/json' } },
    )
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    return new Response(
      JSON.stringify({ error: msg }),
      { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } },
    )
  }
})
