// Supabase Edge Function: create-etj-user
// Deploy: supabase functions deploy create-etj-user --project-ref ggkuodyaddngzskpgvlt
//
// Called by spara_admin users to create new users.
// Supports two modes:
//   - password provided → auth.admin.createUser (account active immediately)
//   - no password       → auth.admin.inviteUserByEmail (magic-link email sent)

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS })

  try {
    const { email, display_name, role, password } = await req.json() as {
      email: string
      display_name?: string
      role?: string
      password?: string
    }

    if (!email) throw new Error('email on pakollinen')
    const validRoles = ['spara_admin', 'municipality', 'customer']
    const userRole = validRoles.includes(role ?? '') ? role! : 'customer'

    // Admin client — has full access via service role key
    const adminClient = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
    )

    // Verify caller is authenticated and is spara_admin
    const authHeader = req.headers.get('Authorization')
    if (!authHeader) throw new Error('Ei kirjautumista')

    const anonClient = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_ANON_KEY')!,
      { global: { headers: { Authorization: authHeader } } },
    )
    const { data: { user: caller }, error: callerErr } = await anonClient.auth.getUser()
    if (callerErr || !caller) throw new Error('Tunnistautumaton pyyntö')

    const { data: callerProfile, error: pErr } = await adminClient
      .from('etj_user_profiles')
      .select('role')
      .eq('id', caller.id)
      .single()
    if (pErr || callerProfile?.role !== 'spara_admin') {
      throw new Error('Vain spara_admin voi luoda käyttäjätunnuksia')
    }

    const meta = { display_name: display_name || email, role: userRole }
    let userId: string

    if (password && password.length >= 8) {
      // Create account with set password — active immediately, no email required
      const { data: created, error: cErr } = await adminClient.auth.admin.createUser({
        email,
        password,
        email_confirm: true,
        user_metadata: meta,
      })
      if (cErr) throw cErr
      userId = created.user.id
    } else {
      // Send magic-link invite — user sets own password on first login
      const siteUrl  = Deno.env.get('SITE_URL') ??
        'https://patrickharjoittelee.github.io/Talorekkari/dashboard/etj-plus.html'
      const baseDir  = siteUrl.replace(/\/[^/]+\.html(\?.*)?$/, '')
      const redirectTo = `${baseDir}/etj-onboarding.html`
      const { data: invited, error: invErr } = await adminClient.auth.admin.inviteUserByEmail(email, {
        data: meta,
        redirectTo,
      })
      if (invErr) throw invErr
      userId = invited.user.id
    }

    // Upsert profile row (available even before user accepts invite)
    const { error: profErr } = await adminClient.from('etj_user_profiles').upsert({
      id:           userId,
      role:         userRole,
      display_name: display_name || email,
    })
    if (profErr) console.error('Profile upsert error (non-fatal):', profErr.message)

    return new Response(
      JSON.stringify({ success: true, user_id: userId }),
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
