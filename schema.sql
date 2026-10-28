-- Puzzle #37 schema (applied to the live Supabase project via the MCP
-- apply_migration tool; kept here for reproducibility).

create table if not exists public.puzzle37_generated_images (
  id uuid primary key default gen_random_uuid(),
  theme text not null,
  prompt text not null,
  image_url text not null,          -- public Supabase Storage URL
  storage_path text not null,       -- path within the bucket
  source_generator text not null default 'pollinations.ai',
  width int not null,
  height int not null,
  created_at timestamptz not null default now()
);

alter table public.puzzle37_generated_images enable row level security;

-- READ is public (serving the generated images is the point).
create policy "puzzle37 anon select"
  on public.puzzle37_generated_images for select to anon using (true);

-- Public bucket, constrained to images with a 5 MB cap.
insert into storage.buckets (id, name, public, allowed_mime_types, file_size_limit)
values ('puzzle37-images', 'puzzle37-images', true,
        array['image/jpeg','image/png'], 5242880)
on conflict (id) do update
  set allowed_mime_types = excluded.allowed_mime_types,
      file_size_limit = excluded.file_size_limit;

create policy "puzzle37 anon read"
  on storage.objects for select to anon
  using (bucket_id = 'puzzle37-images');

-- WRITES: the pipeline must use the service_role key (server-side only, bypasses
-- RLS) to insert rows and upload objects. The initial demo run used a temporary
-- anon-insert policy for convenience; that was revoked after the artifacts were
-- captured (see migration puzzle37_harden_rls) because an anon-insert policy on
-- a shared project lets anyone with the public anon key write. Do NOT re-add an
-- anon write policy for anything beyond a throwaway demo.
