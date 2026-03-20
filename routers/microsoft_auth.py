import os
import requests
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User
from services.jwt_service import create_access_token, set_token_cookie

router = APIRouter()

# ── Config ─────────────────────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("MS_CLIENT_ID")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
TENANT_ID     = os.getenv("MS_TENANT_ID")

AUTHORITY    = f"https://login.microsoftonline.com/{TENANT_ID}"
TOKEN_URL    = f"{AUTHORITY}/oauth2/v2.0/token"
REDIRECT_URI = os.getenv("MS_REDIRECT_URI", "http://localhost:8000/auth/microsoft/callback")


# ── Step 1: Redirect to Microsoft login ───────────────────────────────────────
@router.get("/microsoft/login")
@router.get("/microsoft/login/")
def microsoft_login():
    if not CLIENT_ID or not TENANT_ID:
        raise HTTPException(status_code=500, detail="Microsoft SSO is not configured. Set MS_CLIENT_ID, MS_CLIENT_SECRET, MS_TENANT_ID in .env")

    auth_url = (
        f"{AUTHORITY}/oauth2/v2.0/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_mode=query"
        f"&scope=User.Read+openid+profile+email"
    )
    return RedirectResponse(auth_url)


# ── Step 2: Handle callback, issue JWT ────────────────────────────────────────
@router.get("/microsoft/callback")
def microsoft_callback(request: Request, code: str = None, error: str = None, db: Session = Depends(get_db)):

    # Handle user-cancelled or error from Microsoft
    if error or not code:
        error_desc = request.query_params.get("error_description", "SSO login was cancelled or failed.")
        print(f"[SSO] Microsoft error: {error} — {error_desc}")
        return RedirectResponse(url="/login?sso_error=1", status_code=303)

    # ── Exchange code for access token ─────────────────────────────────────────
    token_response = requests.post(
        TOKEN_URL,
        data={
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  REDIRECT_URI,
            "scope":         "User.Read openid profile email",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )

    token_res = token_response.json()
    access_token = token_res.get("access_token")

    if not access_token:
        print(f"[SSO] Token error: {token_res}")
        raise HTTPException(status_code=400, detail=f"Microsoft token error: {token_res.get('error_description', token_res)}")

    # ── Fetch user profile from Microsoft Graph ────────────────────────────────
    graph_response = requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    user_info = graph_response.json()

    if "error" in user_info:
        print(f"[SSO] Graph error: {user_info}")
        raise HTTPException(status_code=400, detail=f"Microsoft Graph error: {user_info['error'].get('message')}")

    # ── Extract email + name ───────────────────────────────────────────────────
    email = (
        user_info.get("mail")
        or user_info.get("userPrincipalName")
        or (user_info.get("otherMails") or [None])[0]
    )
    name = user_info.get("displayName") or (email.split("@")[0] if email else "User")

    if not email:
        raise HTTPException(status_code=400, detail="No email returned from Microsoft. Ensure the app has User.Read permission.")

    email = email.lower().strip()

    # ── Upsert user ────────────────────────────────────────────────────────────
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(name=name, email=email, password="__sso__")
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"[SSO] New user created: {email}")
    else:
        # Update name if changed in Microsoft
        if user.name != name:
            user.name = name
        print(f"[SSO] Existing user login: {email}")

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    # ── Issue JWT and redirect ─────────────────────────────────────────────────
    token    = create_access_token(user.id, user.name, user.email, auth_method="microsoft_sso")
    response = RedirectResponse(url="/verify", status_code=303)
    return set_token_cookie(response, token)