# Deploying to Render (free tier)

One Docker web service serves the API, the live WebSockets, and the built React app on
a single origin. Free tier works for **outbound** calls: authorizing a campaign is an
HTTP request that wakes the box, and it stays up while the call runs. It sleeps when
idle, so expect a ~15 min-idle cold start, and the default SQLite file resets on
restart (point `DATABASE_URL` at Postgres for durable data).

## 1. Push the branch and create the service
- Merge/publish this branch so Render can build from it.
- Render → **New → Blueprint**, pick this repo. It reads `render.yaml` (Docker, free
  plan, health check `/api/health`). Or **New → Web Service → Docker** and point at the
  `Dockerfile`.

## 2. Set environment variables (Render dashboard → Environment)
All secrets are `sync: false` in `render.yaml`, so Render prompts for them.

| Var | Value |
|---|---|
| `GEMINI_API_KEY` | your key (required) |
| `TOOL_REGISTRY_ENC_KEY` | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
| `COOKIE_SECURE` | `true` (already defaulted in `render.yaml` — https) |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | your Google OAuth client |
| `TWILIO_ACCOUNT_SID` / `_AUTH_TOKEN` / `_FROM_NUMBER` | your Twilio creds + voice number |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` | optional email |
| `DATABASE_URL` | optional Postgres for durable storage |

**You do NOT set** `PUBLIC_WSS_BASE`, `OAUTH_REDIRECT_BASE_URL`, or `APP_BASE_URL` —
they auto-derive from Render's `RENDER_EXTERNAL_HOSTNAME` / `RENDER_EXTERNAL_URL`.

## 3. Register the OAuth callbacks with Google
Once you know the URL (`https://<app>.onrender.com`), add BOTH redirect URIs to your
OAuth client (Google Cloud Console → Credentials):
- `https://<app>.onrender.com/api/auth/google/callback`  (sign-in)
- `https://<app>.onrender.com/api/oauth/callback`  (Calendar/Gmail connect)

And add your Google account as a **test user** on the OAuth consent screen if the app
is still in "Testing".

## 4. Twilio
- Point nothing at Render manually — the app derives the media-stream wss URL itself.
- On a **trial** Twilio account, add your phone as a **Verified Caller ID** so campaigns
  can call it.

## 5. Use it
Open `https://<app>.onrender.com` → sign in with Google → build an agent → try the
🎙️ preview, or add your (verified) number as a lead in a campaign and **Authorize** it
to get a real call. First load after idle takes ~30–60s (cold start).

## Notes / limits (free tier)
- **Cold starts** on the first request after idle.
- **Ephemeral disk**: SQLite (`./.data/vas.db`) resets on redeploy/restart. Use
  `DATABASE_URL` (Postgres) for anything you want to keep.
- **Single instance only** — the Twilio call registry and the campaign loop are
  in-process; don't scale to >1 instance without a shared store.
- **Long autonomous campaigns** (many leads paced over time) can be interrupted by an
  idle sleep between calls; that path wants an always-on instance eventually.
