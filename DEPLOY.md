# Deploying to Streamlit Community Cloud

Vercel can't host this app (Streamlit is a long-running Python/WebSocket server;
Vercel is serverless). Use **Streamlit Community Cloud** — it's free and built for
Streamlit. The app has already been made deploy-ready (secrets, small PII model,
lean requirements). You do four things: push to GitHub, create a cloud Postgres,
deploy, add secrets.

---

## 0. Before you start
- **Rotate your Groq key** at https://console.groq.com/keys (the old one was shared
  in chat). Use the new one everywhere below.
- Have a **GitHub account** and a **Streamlit Cloud account** (sign in with GitHub
  at https://share.streamlit.io).

## 1. Push the project to GitHub
`.env` and `.streamlit/secrets.toml` are gitignored, so your secrets stay local.

```bash
cd C:\NextJS\fintech-support-agent
git init
git add .
git commit -m "Fintech support agent: agent + observability + eval + safety + Postgres"
# create an empty repo on github.com, then:
git remote add origin https://github.com/<you>/fintech-support-agent.git
git branch -M main
git push -u origin main
```
Verify no secrets were committed: `git ls-files | grep -E "\.env$|secrets\.toml$"` should print **nothing**.

## 2. Create a cloud Postgres (localhost won't work from the cloud)
Use **Neon** (https://neon.tech, free) or **Supabase** (https://supabase.com, free):
1. Create a project → copy the **connection string** (looks like
   `postgresql://user:pass@host/dbname?sslmode=require`).
2. Seed it from your machine (one time):
   ```bash
   # PowerShell — point at the cloud DB just for this command:
   $env:DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require"
   python scripts/setup_db.py
   ```
   This creates the tables + demo data in the cloud database.

## 3. Deploy on Streamlit Cloud
1. Go to https://share.streamlit.io → **Create app** → pick your GitHub repo.
2. **Main file path:** `app.py`
3. Click **Deploy**. (First build takes a few minutes — it installs `requirements.txt`.)

## 4. Add secrets
In the app dashboard → **Manage app → Settings → Secrets**, paste (from
`.streamlit/secrets.toml.example`), using your **new** Groq key and **cloud**
DATABASE_URL:
```toml
LLM_API_KEY = "gsk_your_new_key"
LLM_BASE_URL = "https://api.groq.com/openai/v1"
FINTECH_AGENT_MODEL = "openai/gpt-oss-120b"
DATABASE_URL = "postgresql://user:pass@host/dbname?sslmode=require"
PRESIDIO_SPACY_MODEL = "en_core_web_sm"
```
Save → the app reboots and is live at `https://<your-app>.streamlit.app`.

---

## Notes & gotchas
- **PII model:** the cloud uses the small `en_core_web_sm` model (set via
  `PRESIDIO_SPACY_MODEL`) so Presidio fits the ~1 GB free-tier RAM. Name detection
  is slightly less accurate than the local `lg` model; if it can't load, the app
  falls back to the regex PII detector automatically.
- **Cost/rate limits:** a public URL means anyone can burn your Groq quota.
  Consider adding a password (Streamlit supports a simple `st.text_input`
  password gate, or use `streamlit-authenticator`).
- **DB name:** in your `DATABASE_URL`, use the database name your provider gives
  you (e.g. Neon's default `neondb`) — `setup_db.py` will create the tables inside
  whatever DB the URL points at.
- **Evals** (`requirements-dev.txt`: DeepEval, Guardrails) are **not** installed on
  the cloud — they're offline tools you run locally.
