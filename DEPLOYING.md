# Putting SPIDER AI on a server

One process serves everything: the FastAPI app answers `/api/*` and also serves the built
interface, so a hosted deployment is a single web service plus one disk it can keep.

```
Dockerfile      builds frontend/dist, installs the backend, runs uvicorn on $PORT
railway.toml    the same recipe for Railway (she already uses it for another project)
/data           the database, the uploaded documents and the page renders
```

---

## 1. Build it and run it locally first

```bash
docker build -t spider-ai .
docker run -p 8000:8000 -v spider-data:/data spider-ai
```

Open `http://localhost:8000`. If that page works, the hosted version works: the same image,
the same single origin.

Without Docker the equivalent is:

```bash
cd frontend && npm ci && npm run build
cd ../backend && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

The backend picks up `frontend/dist` automatically. `SPIDER_SERVE_FRONTEND=false` turns that
off and leaves an API-only server.

---

## 2. On the host (Railway)

1. Create a project from this repository (it finds `Dockerfile` and `railway.toml`).
2. Add a **volume** and mount it at `/data`. Without it, every redeploy wipes the accounts
   and the documents.
3. Set the variables:

| Variable | What to set |
| --- | --- |
| `SPIDER_SECRET_KEY` | a long random string. Tokens are signed with it; if it changes or is left unset, everyone is signed out on the next restart |
| `SPIDER_ENVIRONMENT` | `production` |
| `SPIDER_DATABASE_URL` | default `sqlite:////data/spider_ai.db`, or a Postgres URL (then run `alembic upgrade head` once, from `backend/`) |
| `SPIDER_STORAGE_DIR` | default `/data/storage` |
| `SPIDER_MAX_UPLOAD_BYTES` | default 41943040 (40 MB) |

Generate the key with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

4. Deploy, then open the public domain and create your own account from the landing page.

---

## 3. Optional: an external AI provider

The analysis engine is built in and always runs; nothing needs a key. Adding a provider only
turns on the parts that ask one:

```
SPIDER_AI_PROVIDER=openai_compatible
SPIDER_AI_BASE_URL=https://api.openai.com/v1
SPIDER_AI_API_KEY=...
SPIDER_AI_MODEL=gpt-4o-mini
```

Passages are sent only when a question is asked or keyword enrichment runs, and the interface
says so on the results strip. The provider's own retention terms apply - the app cannot
promise anything about them, and does not.

---

## 4. What changes when this is hosted rather than on your own machine

Read the landing page again after deploying. It deliberately says nothing about where files
live, because on a server that answer depends on the host: documents are stored in the
server's private storage directory, under the account that uploaded them, and every read or
delete is checked against ownership. If you publish it, that becomes a system holding other
people's documents, so:

- keep HTTPS on (the platform gives you this), and keep `SPIDER_SECRET_KEY` private;
- the upload size cap and the rate limiter on the auth and upload routes are the defaults -
  raise or lower them with `SPIDER_MAX_UPLOAD_BYTES` rather than by editing code;
- deleted documents are purged from disk 30 days after removal (`_enforce_retention` on
  startup);
- a privacy page is worth adding before other people sign up - it is not written here because
  it depends on the host, the retention you choose, and whether a provider key is set.

## 5. What is not ready for the public

- **One process, one disk.** Jobs run in a two-thread pool inside the web process, so this
  serves one instance. Scaling to several instances needs the queue moved out (Celery or RQ)
  and shared storage.
- **No OCR.** Scanned PDFs are reported as unreadable rather than guessed.
- **No email verification or password reset**, so accounts cannot recover a lost password.
- **Traffic beyond a few readers** will want Postgres instead of SQLite.
