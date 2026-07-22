# Setting up authentication (Supabase) — owner's guide

Shotvi uses [Supabase](https://supabase.com) for sign-in (email + password,
and Google). This guide assumes you have never used Supabase before. Total
time: ~20 minutes. Nothing in the app is hardcoded to a project — everything
flows from the `.env` values you fill in at the end.

Until you do this, the app still runs locally **without** auth: leave the
Supabase env vars unset and start the backend with `DEV_MODE=true` — every
request runs as a single fake dev user (a loud banner says so at startup).

---

## 1. Create the Supabase project

1. Go to <https://supabase.com/dashboard> and sign in (GitHub login is fine).
2. Click **New project**.
   - Organization: your personal org is fine.
   - Name: `shotvi` (anything works).
   - Database password: generate one and store it somewhere safe. You will
     not need it for auth — it's for the Postgres database (which we'll use
     in a later phase).
   - Region: pick the one closest to your users (e.g. Mumbai `ap-south-1`).
3. Wait for the project to finish provisioning (~2 minutes).

## 2. Collect the three values you need

In the project dashboard:

1. **Project URL** — go to **Project Settings (gear icon) → Data API**.
   Copy the **Project URL**, e.g. `https://abcdefghijkl.supabase.co`.
2. **Anon (public) key** — go to **Project Settings → API Keys**.
   Copy the **anon / public** key (a long `eyJ...` string ). This key is safe
   to ship in the frontend.
3. **JWT secret (only if your project shows one)** — **Project Settings →
   API → JWT Settings**. Older projects show a **JWT Secret**; if yours
   does, you may copy it for the backend's `SUPABASE_JWT_SECRET`. New
   projects use asymmetric signing keys instead — **skip this**, the backend
   verifies tokens via the project's public JWKS endpoint using just the
   Project URL. When both are set, the secret wins.

## 3. Enable the email provider

1. **Authentication → Sign In / Up → Auth Providers → Email**.
2. Make sure **Enable Email provider** is ON (it is by default).
3. Leave **Confirm email** ON (recommended): new users must click a link in
   their inbox before they can sign in. The app shows a "check your inbox"
   notice after sign-up. Password reset emails ("Forgot?") also use
   Supabase's default email flow — no code changes needed.

> Supabase's built-in email service is fine for development and small
> volume. Before a real launch, configure custom SMTP under
> **Authentication → Emails → SMTP Settings** so emails come from your domain.

## 4. Enable Google sign-in

Google requires a (free) OAuth app in Google Cloud:

1. Go to <https://console.cloud.google.com>, create a project (or reuse one).
2. **APIs & Services → OAuth consent screen**:
   - User type: **External** → Create.
   - App name `Shotvi`, your support email, your contact email. Save through
     the remaining steps (scopes/test users can stay default).
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**, name `Shotvi web`.
   - **Authorised JavaScript origins**: add
     - `http://localhost:3000`
   - **Authorised redirect URIs**: add exactly one —
     - `https://<your-project-ref>.supabase.co/auth/v1/callback`
       (shown verbatim on the Supabase Google-provider page as "Callback URL
       (for OAuth)" — copy it from there to avoid typos)
   - Create, then copy the **Client ID** and **Client secret**.
4. Back in Supabase: **Authentication → Sign In / Up → Auth Providers →
   Google** → toggle ON, paste the Client ID and Client secret, Save.
5. **Authentication → URL Configuration**:
   - **Site URL**: `http://localhost:3000`
   - **Redirect URLs**: add `http://localhost:3000/**`
   (When you deploy, add the production origin here too and to the Google
   JavaScript origins.)

## 5. Fill in the env files

Backend — create/edit `.env` in the repo root (see `.env.example`):

```
SUPABASE_URL=https://<your-project-ref>.supabase.co
# Only if your project has a legacy JWT secret (step 2.3); otherwise leave unset:
# SUPABASE_JWT_SECRET=<jwt-secret>
DEV_MODE=false
```

Frontend — create/edit `frontend/.env` (see `frontend/.env.example`):

```
REACT_APP_SUPABASE_URL=https://<your-project-ref>.supabase.co
REACT_APP_SUPABASE_ANON_KEY=<anon-public-key>
```

Restart both the FastAPI server and `yarn start` (CRA only reads env at
startup). The backend startup log should say
`[auth] Supabase JWT verification: ...` — if it says DEV MODE or warns that
auth is not configured, the env didn't load.

## 6. Smoke test

1. Open `http://localhost:3000` → **Get started** → you land on the auth
   screen (all app pages now redirect there when signed out).
2. Sign up with an email + password → confirm via the email link → sign in.
3. Click **Continue with Google** → Google account chooser → you land back
   on the dashboard signed in.
4. Submit a job. Open an incognito window, sign up as a second user: the
   first user's job must NOT appear in the dashboard, and opening its URL
   directly must show "not found".
5. The logout button is at the bottom of the sidebar (the small door icon
   next to your name).

## How identity works (for later phases)

- The frontend attaches the Supabase access token to every API call
  (`Authorization: Bearer …`); supabase-js refreshes tokens automatically
  and persists the session across reloads.
- The backend verifies the token on every job route and stamps the user id
  (the JWT `sub` claim — a UUID from Supabase's `auth.users`) onto each job
  in Redis. That UUID is the key billing will hang off in the next build.
- Users only ever see their own jobs; a stranger probing another user's job
  id gets a 404 (existence is not leaked). Jobs created before auth existed
  are invisible to real users (clean slate) but still visible in dev mode.

## Known gap (deliberate, deploy-phase work)

The static media mounts `/outputs/...` and `/thumbnails/...` remain
unauthenticated because `<video>`/`<img>` tags cannot send Authorization
headers. Job metadata, listings, and the download endpoint are fully
owner-scoped; the raw media files themselves are reachable by whoever can
guess a video id. Closing this needs signed URLs (or a CDN with token auth)
and is planned for the deployment phase — do not ship public marketing of
per-user privacy for the media files until then.
