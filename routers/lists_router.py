from fastapi import APIRouter, Depends, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import EmailVerification, User, UploadedFile, EmailDetails
from utils.email_extractor import extract_emails_from_file
from services.email_validator import validate_email, pre_validate_result
from services.neverbounce_bulkupload_service import verify_email_list
from services.jwt_service import get_user_from_token
import os
import threading

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../templates"))

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "../uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── Background verification worker ────────────────────────────────────────────
def _run_verification(file_id: int, user_id: int, emails: list):
    """
    Runs in a background thread.
    1. Deduplicate
    2. Pre-validate — invalid emails REMOVED, never sent to NeverBounce
    3. Only valid emails go to NeverBounce
    """
    db = SessionLocal()
    try:
        db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if db_file:
            db_file.status = "processing"
            db.commit()

        # ── 1. Deduplicate ─────────────────────────────────────────────────────
        seen = set()
        unique_emails = []
        for e in emails:
            key = e.strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique_emails.append(key)

        dupes = len(emails) - len(unique_emails)
        if dupes:
            print(f"[Bulk] file_id={file_id} — {dupes} duplicates removed")

        # ── 2. Pre-validate — split into valid and invalid ───────────────────
        valid_emails   = []
        invalid_emails = []
        for e in unique_emails:
            is_valid, reason = validate_email(e)
            if is_valid:
                valid_emails.append(e)
            else:
                invalid_emails.append(pre_validate_result(e, reason))
                print(f"[Bulk] file_id={file_id} — invalid (stored, not sent): {e} ({reason})")

        print(f"[Bulk] file_id={file_id} — {len(invalid_emails)} invalid stored | {len(valid_emails)} valid → NeverBounce")

        # ── 3. Send ONLY valid emails to NeverBounce ───────────────────────────
        api_results = []
        if valid_emails:
            try:
                api_results = verify_email_list(valid_emails)
            except RuntimeError as e:
                if str(e) == "insufficient_credits":
                    print(f"[Bulk] file_id={file_id} — 0 NeverBounce credits")
                    if db_file:
                        db_file.status = "no_credits"
                        db.commit()
                    # Still save the invalid_emails results below
                    if not invalid_emails:
                        return

        # ── 4. Combine all results (invalid + api) and save ───────────────────
        all_results = invalid_emails + api_results

        if not all_results:
            if db_file:
                db_file.status = "failed"
                db.commit()
            return

        db.bulk_save_objects([
            EmailVerification(
                email=r["email"],
                user_id=user_id,
                file_id=file_id,
                job_id=r.get("job_id"),
                status=r["status"],
                result=r["result"],
                suggested_correction=r.get("suggested_correction"),
                flags=r.get("flags"),
                address_info=r.get("address_info"),
                execution_time=r.get("execution_time"),
                credits_info=r.get("credits_info"),
            )
            for r in all_results
        ])

        for r in all_results:
            db.query(EmailDetails).filter(
                EmailDetails.email == r["email"],
                EmailDetails.user_id == user_id
            ).update({"status": r["result"]})

        if db_file and db_file.status != "no_credits":
            db_file.status = "complete"
            db_file.verified_count = len(all_results)
            db.commit()

        print(f"[Bulk] file_id={file_id} complete — {len(api_results)} via NeverBounce, {len(invalid_emails)} invalid stored")

    except Exception as e:
        print(f"[Verification] file_id={file_id} error: {e}")
        db.rollback()
        try:
            db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
            if db_file:
                db_file.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ── Lists Page ─────────────────────────────────────────────────────────────────
@router.get("/lists", response_class=HTMLResponse)
def lists_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    files = db.query(UploadedFile).filter(
        UploadedFile.user_id == user.id
    ).order_by(UploadedFile.created_at.desc()).all()

    # Build per-file stats: count results by result value
    file_stats = {}
    for f in files:
        rows = db.query(EmailVerification).filter(
            EmailVerification.file_id == f.id
        ).all()
        stats = {"valid": 0, "invalid": 0, "unknown": 0, "disposable": 0, "total": len(rows), "job_id": None}
        for r in rows:
            if r.result == "valid":
                stats["valid"] += 1
            elif r.result == "invalid":
                stats["invalid"] += 1
            elif r.result == "unknown":
                stats["unknown"] += 1
            elif r.result == "disposable":
                stats["disposable"] += 1
            if r.job_id and not stats["job_id"]:
                stats["job_id"] = r.job_id
        file_stats[f.id] = stats

    return templates.TemplateResponse("lists.html", {
        "request": request,
        "user": user,
        "files": files,
        "file_stats": file_stats,
        "active": "lists"
    })


# ── Upload File ────────────────────────────────────────────────────────────────
@router.post("/lists/upload")
async def upload_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ["csv", "xls", "xlsx"]:
        return JSONResponse({"error": "Only CSV or Excel files are allowed"}, status_code=400)

    content = await file.read()
    raw_emails = extract_emails_from_file(content, ext)

    if not raw_emails:
        return JSONResponse({"error": "No valid emails found in file"}, status_code=400)

    # Deduplicate at upload time
    seen = set()
    emails = []
    for e in raw_emails:
        key = e.strip().lower()
        if key and key not in seen:
            seen.add(key)
            emails.append(key)

    dupes_removed = len(raw_emails) - len(emails)
    if dupes_removed:
        print(f"[Upload] Removed {dupes_removed} duplicate emails from {file.filename}")

    # Save file to disk
    save_path = os.path.join(UPLOAD_DIR, f"{user.id}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(content)

    # Save file record with status="pending"
    db_file = UploadedFile(
        user_id=user.id,
        file_name=file.filename,
        file_path=save_path,
        total_emails=len(emails),
        status="pending"
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    # Insert pending EmailDetails records
    db.bulk_save_objects([
        EmailDetails(email=e, status="pending", user_id=user.id)
        for e in emails
    ])
    db.commit()

    # ── Fire-and-forget background verification ────────────────────────────────
    t = threading.Thread(
        target=_run_verification,
        args=(db_file.id, user.id, emails),
        daemon=True
    )
    t.start()

    # ── Respond immediately ────────────────────────────────────────────────────
    return JSONResponse({
        "success": True,
        "file_id": db_file.id,
        "file_name": file.filename,
        "emails_found": len(emails),
        "status": "pending",
        "message": f"Verifying {len(emails)} emails in the background. Results will appear shortly."
    })


# ── Poll file status (called by frontend to check progress) ───────────────────
@router.get("/lists/status/{file_id}")
def file_status(file_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    db_file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id,
        UploadedFile.user_id == user.id
    ).first()
    if not db_file:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return JSONResponse({
        "file_id":       db_file.id,
        "file_name":     db_file.file_name,
        "status":        getattr(db_file, "status", "unknown"),
        "total_emails":  db_file.total_emails,
        "verified_count": getattr(db_file, "verified_count", 0),
    })


# ── Delete File ────────────────────────────────────────────────────────────────
@router.post("/lists/delete/{file_id}")
def delete_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    db_file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id,
        UploadedFile.user_id == user.id
    ).first()
    if db_file:
        if os.path.exists(db_file.file_path):
            os.remove(db_file.file_path)
        db.delete(db_file)
        db.commit()
    return RedirectResponse(url="/lists", status_code=302)