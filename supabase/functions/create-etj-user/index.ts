// Supabase Edge Function: create-etj-user
// Deploy: supabase functions deploy create-etj-user
//
// Called by spara_admin users to invite new users.
// Uses SUPABASE_SERVICE_ROLE_KEY (injected automatically by Supabase runtime).

import { serve } from 'https://deno.land/std@0.168.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS })

  try {
    const { email, display_name, role } = await req.json() as {
      email: string
      display_name?: string
      role?: string
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

    // Invite user — sends a magic-link email; user sets own password on first login
    const siteUrl = Deno.env.get('SITE_URL') ??
      'https://patrickharjoittelee.github.io/Talorekkari/dashboard/etj-plus.html'

    const { data: invited, error: invErr } = await adminClient.auth.admin.inviteUserByEmail(email, {
      data: { display_name: display_name || email, role: userRole },
      redirectTo: siteUrl,
    })
    if (invErr) throw invErr

    // Create profile row immediately (user ID is known even before they accept)
    const { error: profErr } = await adminClient.from('etj_user_profiles').upsert({
      id:           invited.user.id,
      role:         userRole,
      display_name: display_name || email,
    })
    if (profErr) console.error('Profile upsert error (non-fatal):', profErr.message)

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
