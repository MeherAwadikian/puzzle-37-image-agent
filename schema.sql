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

create policy "puzzle37 anon insert"
  on public.puzzle37_generated_images for insert to anon with check (true);
create policy "puzzle37 anon select"
  on public.puzzle37_generated_images for select to anon using (true);

insert into storage.buckets (id, name, public)
values ('puzzle37-images', 'puzzle37-images', true)
on conflict (id) do nothing;

create policy "puzzle37 anon upload"
  on storage.objects for insert to anon
  with check (bucket_id = 'puzzle37-images');
create policy "puzzle37 anon read"
  on storage.objects for select to anon
  using (bucket_id = 'puzzle37-images');
