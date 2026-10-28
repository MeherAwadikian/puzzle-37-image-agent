"""
Puzzle #37 — agent writes image prompts, generates images, saves to Supabase.

Pipeline (one theme in -> N stored, captioned images out):
  1. AGENT: an LLM (OpenRouter) turns a plain-language theme into N concrete,
     well-formed image-generation prompts (returned as strict JSON).
  2. GENERATE: each prompt is rendered by a real text-to-image service.
     Brief says "Vertex AI" — no Google Cloud account/gcloud exists on this
     machine (confirmed), so Pollinations.ai is substituted as a real,
     key-less text-to-image endpoint. Swappable: point IMAGE_ENDPOINT at any
     other generator (incl. real Vertex AI) and nothing else changes.
  3. SAVE: each image's bytes are uploaded to a real Supabase Storage bucket,
     and a metadata row (theme, prompt, public URL, dims) is inserted into a
     real Postgres table via Supabase's REST API.

Everything here hits live services — no mocks. Config via env vars (see
.env.example); the demo run in this repo used the shared MeherAwadikian
Supabase project with isolated puzzle37_* objects.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
# SECURITY: use the service_role key here (server-side only — this script is not
# shipped to clients). It bypasses RLS so writes work without an anon-write
# policy. The initial demo used the anon key with a temporary anon-insert policy
# for convenience; that policy was revoked afterward (see schema.sql /
# migration puzzle37_harden_rls) since anon-insert on a shared project lets
# anyone with the public anon key write. Never commit this key.
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
OPENROUTER_KEY = os.environ["OPENROUTER_API_KEY"]

BUCKET = "puzzle37-images"
TABLE = "puzzle37_generated_images"
IMAGE_ENDPOINT = "https://image.pollinations.ai/prompt/"
LLM_MODEL = "nvidia/nemotron-3.5-lightning:free"
WIDTH, HEIGHT = 768, 768


def agent_write_prompts(theme: str, n: int) -> list[str]:
    """Step 1: LLM turns a theme into n concrete image-gen prompts (JSON)."""
    system = (
        "You are an art-director agent. Given a theme, output EXACTLY a JSON "
        "array of concise, vivid, concrete text-to-image prompts (no numbering, "
        "no prose outside the array). Each prompt should be a single detailed "
        "sentence describing one distinct image on the theme."
    )
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Theme: {theme}\nNumber of prompts: {n}"},
        ],
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    content = data["choices"][0]["message"]["content"].strip()
    # Be tolerant of code fences around the JSON.
    if content.startswith("```"):
        content = content.split("```")[1].lstrip("json").strip()
    prompts = json.loads(content)
    if not isinstance(prompts, list):
        raise ValueError(f"agent did not return a list: {content[:200]}")
    return [str(p) for p in prompts[:n]]


def generate_image(prompt: str, retries: int = 5) -> bytes:
    """Step 2: render one prompt to real JPEG bytes.

    Pollinations returns transient 5xx/timeouts under load; retry with
    exponential backoff rather than failing the whole pipeline on one blip.
    """
    url = (
        IMAGE_ENDPOINT
        + urllib.parse.quote(prompt)
        + f"?width={WIDTH}&height={HEIGHT}&nologo=true"
    )
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            if len(data) < 1000:  # guard against empty/placeholder responses
                raise ValueError(f"suspiciously small image ({len(data)} bytes)")
            return data
        except Exception as e:  # noqa: BLE001 - transient network/5xx/429/402
            # Pollinations rate-limits bursts with 402/429; back off generously
            # (10s base) since spaced requests succeed where rapid ones don't.
            last_err = e
            wait = 10 * (attempt + 1)
            print(f"    retry {attempt + 1}/{retries} after error: {e} "
                  f"(waiting {wait}s)", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"image generation failed after {retries} tries: {last_err}")


def upload_to_storage(path: str, image: bytes) -> str:
    """Step 3a: upload bytes to Supabase Storage, return the public URL."""
    up_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
    req = urllib.request.Request(
        up_url,
        data=image,
        method="POST",
        headers={
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "apikey": SUPABASE_KEY,
            "Content-Type": "image/jpeg",
            "x-upsert": "true",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        r.read()
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"


def insert_row(theme: str, prompt: str, image_url: str, path: str) -> dict:
    """Step 3b: insert the metadata row via PostgREST."""
    row = {
        "theme": theme,
        "prompt": prompt,
        "image_url": image_url,
        "storage_path": path,
        "width": WIDTH,
        "height": HEIGHT,
    }
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{TABLE}",
        data=json.dumps(row).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "apikey": SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)[0]


def run(theme: str, n: int):
    print(f"[agent] writing {n} prompts for theme: {theme!r}")
    prompts = agent_write_prompts(theme, n)
    for i, p in enumerate(prompts, 1):
        print(f"  prompt {i}: {p}")

    for i, prompt in enumerate(prompts, 1):
        if i > 1:
            # Space requests so we don't trip Pollinations' burst rate-limit.
            # Tested: the default (free) endpoint 200s when spaced ~15s+ but
            # 402s on rapid bursts; 18s gives headroom.
            time.sleep(18)
        print(f"[generate] image {i}/{len(prompts)} ...", flush=True)
        img = generate_image(prompt)
        path = f"{int(time.time())}_{i}.jpg"
        public_url = upload_to_storage(path, img)
        rec = insert_row(theme, prompt, public_url, path)
        print(f"  saved {len(img)} bytes -> {public_url}")
        print(f"  row id: {rec['id']}")


if __name__ == "__main__":
    theme = sys.argv[1] if len(sys.argv) > 1 else "a cozy coffee shop in different seasons"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    run(theme, n)
