# FutureMe 90 v0.3

FutureMe 90 is a 90-day behavior and fitness adherence MVP.

## v0.3 architecture

- Frontend: `index.html`
- API: FastAPI in `main.py`
- Database: PostgreSQL on Render via `DATABASE_URL` (SQLite fallback for local development)
- Authentication: HttpOnly session cookie; PBKDF2 password hashing
- AI Coach: OpenAI Responses API, server-side only
- Trainer alerts: role-gated endpoint for members whose score/recovery/adherence indicates intervention

## Render Web Service

Build command:

```
pip install -r requirements.txt
```

Start command:

```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Health check:

```
/api/health
```

## Required environment variables

- `DATABASE_URL` — Render PostgreSQL internal connection string
- `OPENAI_API_KEY` — OpenAI API key (server-side secret)
- `OPENAI_MODEL` — defaults to `gpt-5.6-luna`
- `TRAINER_EMAILS` — comma-separated trainer emails, e.g. `trainer@example.com,coach@example.com`

## Notes

The existing localStorage flow remains as an offline fallback. After sign-in, local check-ins are merged into the user's database history.

This is an MVP authentication system. Before production use, add email verification, password reset, rate limiting, audit logging, database migrations, privacy/consent flows, and stronger operational monitoring.
