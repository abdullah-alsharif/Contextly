# Deployment Walkthrough — Get the Credentials & Run Contextly in Production

This guide leads you, step by step, from zero accounts to a working demo on the $0
stack (Vercel + Render + Supabase + NVIDIA/OpenRouter). It is the **beginner path**;
the condensed operator runbook lives in [deployment.md §9](deployment.md), and every
step below is tracked in `specs/012-production-deployment/tasks.md` (tasks T012-T028).

> **Rule of thumb**: every value you collect below goes into a **platform secret
> store** (Render/Vercel dashboards) or stays in your password manager — never into a
> committed file. `.env.example` in the repo is the documentation of variable names,
> with placeholders only.

---

## Part A — Accounts & credentials (about 30-45 min, one-time)

### 1. GitHub repo (prerequisite)

Push this repo to GitHub (private is fine):

```bash
git remote add origin git@github.com:<you>/contextly.git
git push -u origin main
```

You need a GitHub account. Render and Vercel will ask to install their GitHub apps
and grant access to this repo — approve those prompts.

### 2. Supabase — Postgres + Auth + Storage (supabase.com)

1. Sign up at **supabase.com** (GitHub sign-in works).
2. **New project** → choose org, name `contextly`, region closest to you, set a strong
   **database password** (save it — you need it for migrations and for the
   `contextly_app` role password). Wait for provisioning (~2 min).
3. Collect these values from **Project Settings → API** (all three are here):
   - **Project URL** → env: `SUPABASE_URL`
   - **anon public key** → env: `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - **service_role secret key** → env: `SUPABASE_SERVICE_ROLE_KEY`
4. From **Project Settings → Database → Connection string**:
   - Grab the **URI** under *Direct connection* (port **5432**, with your db password
     already filled in). This is your **migration** connection →
     env: `MIGRATION_DATABASE_URL` (add `?sslmode=require` if not present).
   - You do **not** use the pooler (6543) for migrations; the migration files run
     multi-statement SQL and create roles, which the pooler does not allow.
5. **SQL editor** (left sidebar → SQL Editor → New query) — create the runtime role
   password. `0001_init.sql` creates the `contextly_app` role at migration time; it
   has no password yet, so set one:

   ```sql
   -- Run after migrations (step "Supabase setup" in Part B). Use your own strong pw.
   alter role contextly_app with password '<runtime-pw>';
   ```

   The **runtime** DB URL for Render is then:
   `postgresql://contextly_app:<runtime-pw>@<db-host>:5432/postgres?sslmode=require`
   (host from the connection string) → env: `DATABASE_URL`.
6. **Storage bucket + policy** (skip if you'll let the runbook's pre-deploy step do it —
   do it here, it's one screen): Storage → New bucket → name `documents` → **Private**.
   Policies: see `docs/multi-tenancy.md` §4 — the backend signs URLs with the
   service-role key, so a private bucket + folder-per-user layout is enough.
7. **Demo (eval) user**: **Authentication → Users → Add user** → email + password
   (e.g. `demo@contextly.app` / something you can type in a browser). This is the
   "real user" of the Phase 11 DoD.

> Keep the **project URL, anon key, service-role key, db password, runtime-pw** handy —
> you paste them into Render/Vercel in Part B. Do not commit any of them.

### 3. Render — backend + worker (render.com)

1. Sign up at **render.com** (GitHub sign-in). Hobby plans are free.
2. That's the whole account part — the service definition is the committed
   `render.yaml` (web `contextly-backend` + worker `contextly-worker`). You only need
   to run the blueprint once (Part B, step 3) and fill in the secrets.
3. No Render CLI needed; the dashboard handles it.

### 4. Vercel — frontend (vercel.com)

1. Sign up at **vercel.com** (GitHub sign-in, free Hobby).
2. No project setup needed by hand — you import the repo in Part B, step 4, and paste
   four env values there.
3. No Vercel CLI needed; the dashboard handles it.

### 5. AI provider — NVIDIA NIM (or OpenRouter)

Pick one and get a key:

- **NVIDIA (default)** — go to **build.nvidia.com**, sign in, open any model page
  (e.g. *NV-Embed-QA* or the *integrate* docs), find **Get API Key** → create one.
  Value → env: `NVIDIA_API_KEY` (AI provider stays `AI_PROVIDER=nvidia`).
- **OpenRouter (alternative)** — openrouter.ai → sign in → **Keys** → **Create key**
  (free models exist). Value → env: `OPENROUTER_API_KEY` **and** change
  `AI_PROVIDER=openrouter` in Render.
- If you only want the **demo plumbing** (no real AI), you can deploy with
  `AI_PROVIDER=nvidia` unset — but then chat answers will fail; the real key is
  needed for the DoD end-to-end chat with citations.

### 6. Wake cron (optional but recommended) — cron-job.org

1. Sign up at **cron-job.org** (free).
2. Create a job: GET `https://<backend>.onrender.com/healthz` every **14 minutes**,
   retries 3, timeout 60 s. This keeps Render awake and Supabase active
   ([deployment.md §8](deployment.md)).

---

## Part B — Run it (in order)

### 0. Local sanity (before touching the cloud)

```bash
cp .env.example .env
make up         # builds + starts db, backend, worker, frontend
make migrate
make test       # 282 tests
make eval       # recall@6 ≥ 0.85 gate
```

### 1. Push the Phase 11 branch to GitHub

```bash
git push -u origin 012-production-deployment   # or merge to main
```

### 2. Supabase setup

- (If the project paused itself — it happens on free tier — open it in the dashboard
  to wake it.)
- SQL Editor → run the `alter role contextly_app …` snippet from Part A step 5.
- Run the migrations from your machine (the pre-deploy step does this again — harmless
  no-op thanks to the `schema_migrations` ledger):

```bash
MIGRATION_DATABASE_URL='<direct connection URI, port 5432>' \
PYTHONPATH=backend python -m app.migrate
```

- Storage: create the private `documents` bucket if you skipped it in Part A.

### 3. Render — blueprint deploy

1. Render dashboard → **New** → **Blueprint** → pick your repo → Render reads
   `render.yaml` and shows two services. Click **Apply**.
2. For **each** service, fill the secrets (the `sync: false` env vars shown in the
   UI): `DATABASE_URL`, `MIGRATION_DATABASE_URL`, `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, `NVIDIA_API_KEY` (or the OpenRouter pair).
3. Set `CORS_ORIGINS` to the Vercel URL **after** step 4 (`https://<app>.vercel.app`),
   then redeploy once.
4. Watch the first deploy: the web service runs `preDeployCommand` (`python -m
   app.migrate`) before starting; its health check hits `/healthz`. Worker starts in
   parallel.

### 4. Vercel — frontend

1. Vercel dashboard → **Add New → Project** → import the repo. Set **Root
   Directory** to `frontend` (the Next.js app lives in the `frontend/` subfolder;
   without it Vercel can't find the project).
2. Environment Variables (set for *Production* — and *Preview* if you like):
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `NEXT_PUBLIC_AUTH_MODE` = `supabase`
   - `NEXT_PUBLIC_BACKEND_URL` = `https://<backend>.onrender.com`
3. **Deploy**. Visit `https://<app>.vercel.app` — you should land on the login page.

### 5. Demo account E2E (the DoD)

1. Open `https://<app>.vercel.app`, sign in with the demo user from Part A step 7.
2. Upload a small PDF → wait for `ready` → open a chat → ask a question → the answer
   streams with source citations; download a document to prove signed URLs.
3. Backend health: `curl -s https://<backend>.onrender.com/healthz` →
   `{"status":"ok","checks":{"database":true,"ai_provider":true}}`.

### 6. Wake cron

Create the cron-job.org job from Part A step 6.

### 7. Record the verification checklist

Run the 10 checks in `specs/012-production-deployment/checklists/deployment-verification.md`
and tick them with evidence. All 10 green = **Phase 11 done**
(docs/roadmap.md Phase 11 DoD).

---

## Troubleshooting

| Symptom | Cause → Fix |
|---|---|
| `healthz` shows `database:false` | Supabase paused (wake in dashboard) or wrong `DATABASE_URL` (pooler port 6543 vs direct 5432) |
| `healthz` shows `ai_provider:false` | Missing/invalid `NVIDIA_API_KEY` or `AI_PROVIDER` typo |
| Deploy fails with `STORAGE_PROVIDER=local is only allowed when APP_ENV=dev` | A prod env value was left dev-ish — set the real one (this guard is working as designed) |
| Migrations fail with `MIGRATION_DATABASE_URL must be set` | The pre-deploy guard caught a missing migration secret (docs/deployment.md §4) — set `MIGRATION_DATABASE_URL` on the web service and redeploy; the runner never silently falls back to the runtime role outside dev |
| CORS errors in the browser | `CORS_ORIGINS` on Render missing the exact `https://<app>.vercel.app` origin |
| Login works but sessions drop | `NEXT_PUBLIC_AUTH_MODE` not set to `supabase` on Vercel |
| First request after idle is slow | Render free sleep / cold start — expected; the wake cron minimizes it (deployment.md §8) |
| `ALTER ROLE` fails in SQL editor | You ran it before migrations — run `python -m app.migrate` first (role is created by `0001_init.sql`) |
