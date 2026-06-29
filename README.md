# Sutura Genomics

**The alignment layer for spatial transcriptomics.** Graph deep learning for
tissue registration — built for the tears optimal transport can't represent.

This repository is the Sutura Genomics marketing site (Next.js).

---

## About Sutura

Sutura is a learned registrar (graph encoder + cross-attention + deformation
head) for aligning spatial-transcriptomics tissue slices, built for the torn /
non-isometric warps that optimal-transport and diffeomorphic methods struggle to
represent. It is benchmarked on the DLPFC Visium dataset against PASTE2 (optimal
transport), STalign and CODA (diffeomorphic), and GPSA.

See **[github.com/Sutura-Genomics/sutura-paper](https://github.com/Sutura-Genomics/sutura-paper)**
for benchmark results, model code, and the preprint.

---

## Getting started (website)

This is a [Next.js](https://nextjs.org) app.

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

- Landing page: `src/app/page.tsx`
- Demo / contact form: `src/app/demo/page.tsx`
- Deploys via Netlify (`netlify.toml`).

## Demo form backend (Supabase)

The demo form writes leads to a Supabase `demo_requests` table via a client-side
insert (the site is a static export, so there's no server). The anon key is
public; Row Level Security restricts it to inserts only — see
`supabase/schema.sql`.

One-time setup:

1. Create a project at [supabase.com](https://supabase.com) (sign in as
   rushilmaniar2010@gmail.com).
2. SQL Editor → paste `supabase/schema.sql` → Run.
3. Project Settings → API → copy the **Project URL** and **anon public key**.
4. Set both as env vars — locally in `.env.local` (see `.env.local.example`) and
   in Netlify (Site settings → Environment variables):
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
5. Redeploy. Until these are set, the form degrades gracefully (acknowledges the
   submission without storing). View leads in the Supabase Table editor.
