// Supabase Edge Function: invite-etj-user
// Deploy: supabase functions deploy invite-etj-user --project-ref ggkuodyaddngzskpgvlt
//
// Public endpoint — called from etj-tilaussopimus.html after contract signing.
// Sends a Supabase invite email with a link to etj-onboarding.html?koodi=XXX.
// No caller auth required, but validates email format and rate-limits via Supabase.

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS })

  try {
    const { email, display_name, etj_code, company_name } = await req.json() as {
      email:        string
      display_name?: string
      etj_code?:    string
      company_name?: string
    }

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      throw new Error('Virheellinen sähköpostiosoite')
    }

    const adminClient = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
    )

    // Build onboarding URL — koodi baked into link so landing page auto-fills it
    const siteUrl  = Deno.env.get('SITE_URL') ??
      'https://patrickharjoittelee.github.io/Talorekkari/dashboard/etj-plus.html'
    const baseDir  = siteUrl.replace(/\/[^/]+\.html(\?.*)?$/, '')
    const codeParam = etj_code ? `?koodi=${encodeURIComponent(etj_code.toUpperCase())}` : ''
    const redirectTo = `${baseDir}/etj-onboarding.html${codeParam}`

    const meta = {
      display_name: display_name || email,
      role:         'customer',
      etj_code:     etj_code || '',
      company_name: company_name || '',
    }

    // Invite user — Supabase sends the magic-link email
    const { data: invited, error: invErr } = await adminClient.auth.admin.inviteUserByEmail(email, {
      data:       meta,
      redirectTo,
    })
    if (invErr) throw invErr

    // Pre-create profile row so RLS recognises role before first login
    await adminClient.from('etj_user_profiles').upsert({
      id:           invited.user.id,
      role:         'customer',
      display_name: display_name || email,
    })

    return new Response(
      JSON.stringify({ success: true, user_id: invited.user.id }),
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
