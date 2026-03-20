from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from services.jwt_service import get_user_from_token
from schemas import EmailRequest
from models import EmailVerification, EmailDetails, User, UploadedFile
from services.email_service_single_check import verify_email
from services.email_validator import validate_email, pre_validate_result
import os

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@router.get("/verify", response_class=HTMLResponse)
def verify_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    history = db.query(EmailVerification).filter(
        EmailVerification.user_id == user.id
    ).order_by(EmailVerification.created_at.desc()).limit(500).all()

    user_files = db.query(UploadedFile).filter(
        UploadedFile.user_id == user.id
    ).order_by(UploadedFile.created_at.desc()).all()

    return templates.TemplateResponse("verify.html", {
        "request":     request,
        "user":        user,
        "history":    history,
        "user_files": user_files,
        "active":     "verify"
    })


@router.post("/api/verify")
def verify_emails_api(data: EmailRequest, request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    # ── 1. Deduplicate ─────────────────────────────────────────────────────────
    seen = set()
    unique_emails = []
    for e in data.emails:
        key = e.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_emails.append(key)

    duplicates_removed = len(data.emails) - len(unique_emails)

    results = []
    for email in unique_emails:

        # ── 2. Pre-validate ────────────────────────────────────────────────────
        is_valid, reason = validate_email(email)

        if not is_valid:
            # Invalid — build result locally, NO NeverBounce call
            verification    = pre_validate_result(email, reason)
            verified_email  = email
            verified_status = "failed"
            print(f"[SingleCheck] Invalid (not sent to NeverBounce): {email} — {reason}")
        else:
            # Valid — send to NeverBounce
            verification    = verify_email(email)
            verified_email  = verification["address_info"]["original_email"]
            verified_status = verification["status"]

        # ── 3. Upsert email_details ────────────────────────────────────────────
        email_detail = db.query(EmailDetails).filter(
            EmailDetails.email == verified_email,
            EmailDetails.user_id == user.id
        ).first()
        if email_detail:
            email_detail.status = verification["result"]
            db.commit()
        else:
            db.add(EmailDetails(
                email=verified_email,
                status=verification["result"],
                user_id=user.id
            ))
            db.commit()

        # ── 4. Save to email_verifications ────────────────────────────────────
        db_record = EmailVerification(
            user_id=user.id,
            file_id=None,
            email=verified_email,
            status=verified_status,
            result=verification["result"],
            suggested_correction=verification.get("suggested_correction"),
            flags=verification.get("flags"),
            address_info=verification.get("address_info"),
            credits_info=verification.get("credits_info"),
            execution_time=verification.get("execution_time")
        )
        db.add(db_record)
        db.commit()
        db.refresh(db_record)

        results.append({
            "email":         db_record.email,
            "status":        db_record.status,
            "result":        db_record.result,
            "file_id":       None,
            "pre_validated": verification.get("pre_validated", False),
            "created_at":    db_record.created_at.strftime("%b %d, %H:%M") if db_record.created_at else "Just now"
        })

    return JSONResponse({
        "results":            results,
        "skipped_duplicates": duplicates_removed,
        "invalid_count":      sum(1 for r in results if r.get("pre_validated")),
    })


@router.get("/api/history")
def get_history(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return db.query(EmailVerification).filter(
        EmailVerification.user_id == user.id
    ).order_by(EmailVerification.created_at.desc()).all()