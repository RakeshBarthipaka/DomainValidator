from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models import User
from services.jwt_service import (
    create_access_token, get_user_from_token,
    set_token_cookie, clear_token_cookie
)
import hashlib
import os

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ── Helpers ────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def is_hashed(password: str) -> bool:
    return len(password) == 64 and all(c in "0123456789abcdef" for c in password.lower())

def check_password(plain: str, stored: str) -> bool:
    if is_hashed(stored):
        return hash_password(plain) == stored
    return plain == stored  # legacy plain-text support


# ── Register ───────────────────────────────────────────────────────────────────
@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    if get_user_from_token(request, db):
        return RedirectResponse(url="/verify", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request, "error": None, "values": {}})

@router.post("/register")
def register_post(
    request:  Request,
    name:     str = Form(...),
    email:    str = Form(...),
    password: str = Form(...),
    confirm:  str = Form(...),
    db: Session = Depends(get_db),
):
    values = {"name": name, "email": email}

    if len(name.strip()) < 2:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Name must be at least 2 characters.", "values": values})
    if len(password) < 6:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Password must be at least 6 characters.", "values": values})
    if password != confirm:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Passwords do not match.", "values": values})

    existing = db.query(User).filter(User.email == email.lower().strip()).first()
    if existing:
        return templates.TemplateResponse("register.html", {"request": request, "error": "An account with this email already exists.", "values": values})

    user = User(name=name.strip(), email=email.lower().strip(), password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token    = create_access_token(user.id, user.name, user.email, auth_method="password")
    response = RedirectResponse(url="/verify", status_code=303)
    return set_token_cookie(response, token)


# ── Login ──────────────────────────────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if get_user_from_token(request, db):
        return RedirectResponse(url="/verify", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "email": ""})

@router.post("/login")
def login_post(
    request:  Request,
    email:    str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if not user or not check_password(password, user.password):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password.",
            "email": email
        })

    # Update last login
   
    user.last_login = datetime.now(timezone.utc)

    # Upgrade plain-text password to hash
    if not is_hashed(user.password):
        user.password = hash_password(password)

    db.commit()

    token    = create_access_token(user.id, user.name, user.email, auth_method="password")
    response = RedirectResponse(url="/verify", status_code=303)
    return set_token_cookie(response, token)


# ── Logout ─────────────────────────────────────────────────────────────────────
@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    clear_token_cookie(response)
    # Also clear old cookies for backwards compatibility
    response.delete_cookie("user_id")
    response.delete_cookie("user_name")
    return response