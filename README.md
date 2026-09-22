# FutureMe 90 v0.3

FutureMe 90 is a 90-day behavior and fitness adherence MVP.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Steve-Yang-KR/Futureme90)

## v0.3 architecture

- Frontend: `index.html`
- API: FastAPI in `main.py`
- Database: Render PostgreSQL via Blueprint-managed `DATABASE_URL`
- Authentication: HttpOnly session cookie; PBKDF2 password hashing
- AI Coach: OpenAI Responses API, server-side only
- Trainer alerts: role-gated endpoint for members whose score/recovery/adherence indicates intervention
- Offline fallback: browser localStorage remains available before sign-in

## One-click Render deployment

This repository includes a root `render.yaml` Blueprint. Deploying the Blueprint creates:

1. `futureme90-v03` — Python/FastAPI Web Service
2. `futureme90-db` — PostgreSQL database
3. Automatic `DATABASE_URL` wiring from the database to the web service

During Blueprint setup, Render will ask for these secret/config values:

- `OPENAI_API_KEY` — OpenAI API key; keep it server-side
- `TRAINER_EMAILS` — comma-separated trainer email addresses

`OPENAI_MODEL` is set to `gpt-5.6-luna`.

### Important: Free database limitation

The Blueprint currently uses Render's Free plans for MVP testing. A Free Render PostgreSQL database expires 30 days after creation. Upgrade the database before expiration if you need to retain production data.

## Health check

After deploy:

```
GET /api/health
```

Expected response resembles:

```json
{"ok":true,"version":"0.3","database":"postgres"}
```

## Local development

Without `DATABASE_URL`, the application falls back to SQLite.

```
pip install -r requirements.txt
uvicorn main:app --reload
```

## Production hardening

Before production use, add email verification, password reset, rate limiting, audit logging, formal database migrations, privacy/consent flows, backups/retention policies, and stronger operational monitoring.
