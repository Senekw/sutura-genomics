import { createClient } from "@supabase/supabase-js";

// Public Supabase project values for the demo form.
//
// These are SAFE to commit. The anon key is designed to be exposed in the
// browser bundle — it ships to every visitor regardless — and the database is
// protected by Row Level Security, not by hiding this key (demo_requests is
// insert-only for the public; see supabase/schema.sql). Committing them means
// the connected GitHub → Netlify deploy works with no env-var setup at all.
//
// Env vars override these when present (e.g. to point at a staging project).
//
// NEVER commit the service_role key — it bypasses RLS. It is not used here.
const FALLBACK_URL = "https://mnvwblgtkfnbtqzydgdp.supabase.co";
const FALLBACK_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1udndibGd0a2ZuYnRxenlkZ2RwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODIzMjU4NzMsImV4cCI6MjA5NzkwMTg3M30._0XP86gnH5T1ItTSz8XduP6Pr5wm9nOIdyABsVOy6s8";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL || FALLBACK_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || FALLBACK_ANON_KEY;

export const supabase = createClient(url, anonKey);
export const isSupabaseConfigured = true;
