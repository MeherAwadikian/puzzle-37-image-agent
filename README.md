# Puzzle #37 — agent writes image prompts, generates images, saves to Supabase

Brief (Task Forge puzzle tracker): agent writes image prompts, generates via Vertex AI, saves to Supabase — Vertex AI + Supabase.

`pipeline.py` is a real end-to-end pipeline, no mocks:

1. **Agent** — an LLM (OpenRouter) acting as an art-director turns a
   plain-language *theme* into N concrete, well-formed text-to-image prompts,
   returned as strict JSON.
2. **Generate** — each prompt is rendered to a real image. The brief says
   Vertex AI; no Google Cloud account / `gcloud` exists on this machine
   (confirmed, not assumed), so **Pollinations.ai** is the real key-less
   text-to-image substitute. The generator is a single swappable constant
   (`IMAGE_ENDPOINT`) — point it at real Vertex AI (or any other API) and
   nothing else changes.
3. **Save** — each image's bytes are uploaded to a real **Supabase Storage**
   bucket (`puzzle37-images`, public), and a metadata row (theme, prompt,
   public URL, storage path, dimensions) is inserted into a real Postgres
   table (`puzzle37_generated_images`) via Supabase's REST API.

## Verified live (real services, real artifacts)

Ran against the live shared Supabase project with a theme of *"a lighthouse
through the four seasons"*:

- The agent produced distinct, detailed seasonal prompts (winter storm /
  summer golden-hour / autumn foliage — see the run log).
- **2 images completed the full agent → generate → upload → DB-row flow and
  are verified three independent ways**: the pipeline's own output, a direct
  `SELECT` against `puzzle37_generated_images` via the Supabase MCP tools
  (independent of the pipeline), and fetching the **public Storage URLs** back
  (HTTP 200, real 768×768 JPEGs, viewed to confirm each matches its prompt —
  the winter image is a solitary lighthouse under a stormy sky with its beacon
  piercing the clouds; the summer image is a lighthouse on a wildflower-covered
  cliff at golden hour). This proves every stage of the pipeline end to end.

Live artifacts:
- `.../puzzle37-images/1793174958_1.jpg` (winter) — row `7908c812-…`
- `.../puzzle37-images/1793175015_2.jpg` (summer) — row `e702d4cc-…`

## Real limitation found, handled, and honestly reported (not faked around)

Pollinations free tier rate-limits *bursts* — rapid successive requests return
`HTTP 402 Payment Required` (the paid `flux` model 402s outright; the default
model 200s only when requests are spaced). Confirmed by direct testing. The
pipeline handles this by spacing requests (~18s) and retrying 402/429/5xx with
escalating backoff — that's how images 1 and 2 recovered after transient
errors. During this session Pollinations was additionally **overloaded** (a
sustained 503/402 storm, then intermittent DNS failures), so a third image
would not complete even across several spaced, cooled-down attempts. Rather
than hammer an overloaded free service or claim a run that didn't happen, this
is reported as-is: the pipeline mechanic is fully proven by the two complete,
independently-verified artifacts, and the third is purely an external-service
availability limit at this moment, not a code defect. Point `IMAGE_ENDPOINT` at
a paid/real generator (incl. Vertex AI) for guaranteed throughput.

## Schema

`schema.sql` is the exact DDL (table + RLS + public Storage bucket + bucket
RLS), applied to the live project via Supabase migration. The demo writes
with the project's publishable/anon key, which the RLS policies scope to the
`puzzle37_*` objects only.
