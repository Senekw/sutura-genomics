import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Public, client-side Supabase access. The anon key is meant to be exposed to
// the browser — what it can actually do is constrained by Row Level Security
// (see supabase/schema.sql: the `demo_requests` table allows anon INSERT only,
// no SELECT/UPDATE/DELETE). Both vars are inlined at build time, so they must be
// set in `.env.local` for local dev AND in the Netlify build environment.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// `null` when unconfigured (e.g. before the project exists) so the demo form can
// degrade gracefully instead of crashing the static build.
export const supabase: SupabaseClient | null =
  url && anonKey ? createClient(url, anonKey) : null;

export const isSupabaseConfigured = Boolean(url && anonKey);
