import os
import re
import json
import hmac
import hashlib
import secrets
import time
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Response, Cookie
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey, UniqueConstraint, desc
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from openai import OpenAI

APP_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(APP_DIR, "index.html")

raw_db_url = os.getenv("DATABASE_URL", "sqlite:///./futureme90.db")
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif raw_db_url.startswith("postgresql://"):
    raw_db_url = raw_db_url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if raw_db_url.startswith("sqlite") else {}
engine = create_engine(raw_db_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

SESSION_COOKIE = "fm90_session"
SESSION_DAYS = 30
IS_RENDER = os.getenv("RENDER", "").lower() == "true"
TRAINER_EMAILS = {e.strip().lower() for e in os.getenv("TRAINER_EMAILS", "").split(",") if e.strip()}

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False, default="Member")
    password_hash = Column(String(256), nullable=False)
    role = Column(String(20), nullable=False, default="member")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

class LoginSession(Base):
    __tablename__ = "login_sessions"
    id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(Integer, nullable=False, index=True)

class Checkin(Base):
    __tablename__ = "checkins"
    __table_args__ = (UniqueConstraint("user_id", "checkin_date", name="uq_user_checkin_date"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    checkin_date = Column(Date, nullable=False, index=True)
    day = Column(Integer, nullable=False)
    sleep = Column(Float, nullable=False, default=0)
    steps = Column(Integer, nullable=False, default=0)
    recovery = Column(Integer, nullable=False, default=0)
    workout = Column(Integer, nullable=False, default=0)
    plan = Column(Boolean, nullable=False, default=False)
    mood = Column(Boolean, nullable=False, default=False)
    mobility = Column(Boolean, nullable=False, default=False)
    nutrition = Column(Boolean, nullable=False, default=False)
    score = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(bind=engine)
app = FastAPI(title="FutureMe 90 API", version="0.3")

class AuthInput(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    name: Optional[str] = Field(default=None, max_length=120)

class CheckinInput(BaseModel):
    date: Optional[str] = None
    day: int = Field(ge=1, le=90)
    sleep: float = Field(ge=0, le=16)
    steps: int = Field(ge=0, le=100000)
    recovery: int = Field(ge=0, le=100)
    workout: int = Field(ge=0, le=600)
    plan: bool = False
    mood: bool = False
    mobility: bool = False
    nutrition: bool = False

class CoachInput(BaseModel):
    question: Optional[str] = Field(default=None, max_length=1500)
    profile: Optional[dict] = None

def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    return email

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 390000)
    return "pbkdf2_sha256$390000$" + salt.hex() + "$" + digest.hex()

def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def set_session_cookie(response: Response, db: Session, user_id: int):
    token = secrets.token_urlsafe(40)
    expiry = int(time.time()) + SESSION_DAYS * 86400
    db.add(LoginSession(token_hash=token_hash(token), user_id=user_id, expires_at=expiry))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400,
        httponly=True, secure=IS_RENDER, samesite="lax", path="/"
    )

def current_user(db: Session = Depends(db_session), fm90_session: Optional[str] = Cookie(default=None)) -> User:
    if not fm90_session:
        raise HTTPException(status_code=401, detail="Sign in required.")
    session = db.query(LoginSession).filter(LoginSession.token_hash == token_hash(fm90_session)).first()
    if not session or session.expires_at < int(time.time()):
        if session:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user

def trainer_user(user: User = Depends(current_user)) -> User:
    if user.role not in {"trainer", "admin"}:
        raise HTTPException(status_code=403, detail="Trainer access required.")
    return user

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

def score_checkin(x: CheckinInput) -> int:
    sleep = clamp(100 - abs(x.sleep - 7.5) * 18, 0, 100)
    steps = clamp(x.steps / 8000 * 100, 0, 100)
    recovery = clamp(x.recovery, 0, 100)
    workout = clamp(x.workout / 40 * 100, 0, 100)
    adherence = 100 if x.plan else 45
    lifestyle = sum([100 if x.mood else 55, 100 if x.mobility else 60, 100 if x.nutrition else 55]) / 3
    return round(sleep * .18 + steps * .15 + recovery * .22 + workout * .20 + adherence * .15 + lifestyle * .10)

def serialize_checkin(c: Checkin) -> dict:
    return {
        "date": c.checkin_date.isoformat(), "day": c.day, "sleep": c.sleep, "steps": c.steps,
        "recovery": c.recovery, "workout": c.workout, "plan": c.plan, "mood": c.mood,
        "mobility": c.mobility, "nutrition": c.nutrition, "score": c.score,
    }

@app.get("/")
def home():
    return FileResponse(INDEX_FILE)

@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.3", "database": "postgres" if "postgres" in raw_db_url else "sqlite"}

@app.post("/api/auth/register")
def register(payload: AuthInput, response: Response, db: Session = Depends(db_session)):
    email = normalize_email(payload.email)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="An account already exists for this email.")
    role = "trainer" if email in TRAINER_EMAILS else "member"
    user = User(
        email=email, name=(payload.name or email.split("@")[0]).strip()[:120],
        password_hash=hash_password(payload.password), role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, db, user.id)
    return {"user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}

@app.post("/api/auth/login")
def login(payload: AuthInput, response: Response, db: Session = Depends(db_session)):
    email = normalize_email(payload.email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    desired_role = "trainer" if email in TRAINER_EMAILS else user.role
    if desired_role != user.role:
        user.role = desired_role
        db.commit()
    set_session_cookie(response, db, user.id)
    return {"user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}

@app.post("/api/auth/logout")
def logout(response: Response, db: Session = Depends(db_session), fm90_session: Optional[str] = Cookie(default=None)):
    if fm90_session:
        session = db.query(LoginSession).filter(LoginSession.token_hash == token_hash(fm90_session)).first()
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}

@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}

@app.get("/api/checkins")
def list_checkins(user: User = Depends(current_user), db: Session = Depends(db_session)):
    rows = db.query(Checkin).filter(Checkin.user_id == user.id).order_by(Checkin.checkin_date.asc()).all()
    return {"checkins": [serialize_checkin(c) for c in rows]}

@app.post("/api/checkins")
def save_checkin(payload: CheckinInput, user: User = Depends(current_user), db: Session = Depends(db_session)):
    try:
        checkin_date = date.fromisoformat(payload.date) if payload.date else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date.")
    score = score_checkin(payload)
    row = db.query(Checkin).filter(Checkin.user_id == user.id, Checkin.checkin_date == checkin_date).first()
    if not row:
        row = Checkin(user_id=user.id, checkin_date=checkin_date)
        db.add(row)
    row.day, row.sleep, row.steps, row.recovery, row.workout = payload.day, payload.sleep, payload.steps, payload.recovery, payload.workout
    row.plan, row.mood, row.mobility, row.nutrition = payload.plan, payload.mood, payload.mobility, payload.nutrition
    row.score = score
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return {"checkin": serialize_checkin(row)}

@app.post("/api/coach")
def ai_coach(payload: CoachInput, user: User = Depends(current_user), db: Session = Depends(db_session)):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured on the server.")
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    recent = db.query(Checkin).filter(Checkin.user_id == user.id).order_by(desc(Checkin.checkin_date)).limit(7).all()
    context = {
        "member": {"name": user.name},
        "profile": payload.profile or {},
        "last_7_checkins": [serialize_checkin(c) for c in reversed(recent)],
        "question": payload.question or "What should I focus on today?",
    }
    instructions = (
        "You are FutureMe 90, a concise behavior and fitness adherence coach for a 90-day program. "
        "Use only the supplied context. Focus on practical consistency, schedule fit, recovery, and sustainable behavior. "
        "Do not diagnose disease, prescribe medication, or claim guaranteed physiological outcomes. "
        "If the user mentions severe pain, fainting, chest pain, breathing difficulty, or an emergency, advise urgent professional medical care. "
        "Answer in the same language as the user's question when clear. Otherwise use English. "
        "Give: (1) one-sentence status, (2) up to three concrete actions for today, and (3) one short reason. Keep it under 180 words."
    )
    client = OpenAI(api_key=api_key)
    try:
        result = client.responses.create(model=model, instructions=instructions, input=json.dumps(context, ensure_ascii=False))
        message = (result.output_text or "").strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="AI coach request failed: " + str(exc)[:180])
    return {"message": message, "model": model}

@app.get("/api/trainer/alerts")
def trainer_alerts(_: User = Depends(trainer_user), db: Session = Depends(db_session)):
    members = db.query(User).filter(User.role == "member").order_by(User.created_at.asc()).all()
    alerts = []
    for member in members:
        recent = db.query(Checkin).filter(Checkin.user_id == member.id).order_by(desc(Checkin.checkin_date)).limit(7).all()
        if not recent:
            continue
        latest = recent[0]
        avg_score = round(sum(c.score for c in recent) / len(recent))
        missed = sum(1 for c in recent if not c.plan)
        if latest.score < 60 or latest.recovery < 45:
            risk, action = "HIGH", "Human coach outreach recommended"
        elif avg_score < 72 or missed >= 3 or latest.recovery < 60:
            risk, action = "MEDIUM", "Review schedule and recovery"
        else:
            continue
        alerts.append({
            "member": member.name, "email": member.email, "day": latest.day,
            "latest_score": latest.score, "avg_7": avg_score, "recovery": latest.recovery,
            "risk": risk, "suggested_action": action,
        })
    alerts.sort(key=lambda x: (0 if x["risk"] == "HIGH" else 1, x["latest_score"]))
    return {"alerts": alerts}
