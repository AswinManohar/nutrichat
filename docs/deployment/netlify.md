# Netlify deployment runbook (frontend)

The NutriChat React/Vite frontend deploys to **Netlify**. The backend (FastAPI)
is on Railway — see [`railway.md`](./railway.md). The frontend is a static SPA;
it talks to the backend purely over HTTPS using build-time `VITE_*` env vars.

> **Monorepo note:** the app lives in `frontend/`, and its
> [`frontend/netlify.toml`](../../frontend/netlify.toml) holds the build config:
> ```toml
> [build]
>   command = "npm run build"   # vite build
>   publish = "dist"            # -> frontend/dist
> [[redirects]]
>   from = "/*"; to = "/index.html"; status = 200   # SPA fallback for client routing
> ```
> Because `netlify.toml` is inside `frontend/`, Netlify's **base directory must
> be `frontend`** (git-connected builds), or you run the CLI **from inside
> `frontend/`** (CLI deploys). Paths above are relative to that base.

---

## Prerequisites (once per machine)

```bash
netlify --version          # CLI is already installed in this environment (v24+)
# If missing: npm i -g netlify-cli
netlify login              # opens a browser to authorize your Netlify account
netlify status             # confirm the logged-in account
```

---

## Environment variables (build-time)

Vite **inlines** `VITE_*` vars at build time, so they must be set on Netlify
**before** the build, and a rebuild is required after any change. Set them in
Site configuration → Environment variables (or `netlify env:set` from
`frontend/`):

```bash
VITE_API_URL=https://web-production-e3eea.up.railway.app   # Railway web service
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<supabase anon/publishable key>     # safe for the browser
```

> The anon key is meant to be public (RLS enforces access). Never put the
> Supabase **service_role** key or any server secret in a `VITE_*` var — it would
> ship to every browser.

---

## First-time setup

Run everything from the `frontend/` directory so the CLI picks up
`frontend/netlify.toml`.

```bash
cd frontend
netlify init        # create a new site (or 'netlify link' to an existing one)
```

`netlify init` asks how to deploy. Two models:

- **Git-connected (recommended for the team):** authorize GitHub, pick
  `AswinManohar/nutrichat`, set **Base directory = `frontend`**, **Production
  branch = `production`** (to match Railway). Build command `npm run build`,
  publish `frontend/dist` — Netlify reads these from `netlify.toml`. Every push
  to `production` then auto-builds. Set the `VITE_*` env vars in the UI, then
  trigger the first deploy.
- **CLI / manual:** skip git connection; deploy on demand with the CLI (below).

Then set the env vars (UI or CLI) and do the first production deploy:

```bash
netlify env:set VITE_API_URL https://web-production-e3eea.up.railway.app
netlify env:set VITE_SUPABASE_URL https://<ref>.supabase.co
netlify env:set VITE_SUPABASE_ANON_KEY <anon-key>
netlify deploy --prod        # builds (npm run build) and publishes frontend/dist
```

Note the resulting site URL (e.g. `https://<site>.netlify.app`).

### Wire CORS on the backend
After you know the Netlify URL, set it as an allowed origin on the Railway
**web** service so the browser can call the API:

```bash
~/.railway/bin/railway variables --service web \
  --set FRONTEND_ORIGIN=https://<site>.netlify.app
~/.railway/bin/railway up --service web --detach -m "allow Netlify origin (CORS)"
```
(Comma-separate multiple origins to also allow Netlify deploy previews.)

---

## Routine deploy

- **Git-connected:** `git push origin production` → Netlify builds automatically.
- **CLI:**
  ```bash
  cd frontend
  netlify deploy --prod      # production release
  netlify deploy             # draft/preview URL without touching production
  ```

A local `npm run build` should succeed first — Netlify runs the same command.

---

## Post-deploy verification

1. Open `https://<site>.netlify.app` — the login page renders (standard Supabase
   sign-in only; no developer-bypass tab).
2. Browser tab title reads **NutriChat**.
3. Sign in with a real Supabase account → dashboard/chat load (confirms
   `VITE_API_URL` + CORS: no CORS errors in the browser console, API calls 200).
4. Deep-link a client route (e.g. `/settings`) and refresh → the SPA redirect
   serves it (no 404), proving the `/* -> /index.html` rule is active.

If API calls fail with CORS errors, the Railway `web` service's
`FRONTEND_ORIGIN` doesn't match the Netlify URL — fix and redeploy `web`.
If calls 401 unexpectedly, check `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY`
match the project whose JWTs the backend verifies.
