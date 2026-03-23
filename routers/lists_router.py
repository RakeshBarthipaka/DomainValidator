"""
lists_router.py  — Updated to implement all requirements doc rules

Full pipeline per record:
  1. Deduplicate
  2. Step 1 — Domain Matching (local, free, no API call)
       email domain vs website domain (Col H vs Col AF)
       → Domain Match     → proceed to Step 2
       → Domain Mismatch  → store "domain_mismatch", skip API
       → Missing field    → store "skipped_missing", skip API
  3. Python email-validator pre-check (format + DNS)
       → Invalid format   → store "invalid", skip API
  4. Step 2 — NeverBounce API (only domain-matched + format-valid emails)
  5. Write results back to source Excel file (first empty column after last used)
"""

from fastapi import APIRouter, Depends, Request, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import EmailVerification, User, UploadedFile, EmailDetails, ValidationLog
from utils.email_extractor import extract_records_from_file, extract_emails_from_file
from services.domain_matcher import check_domain, build_step1_skipped_result, extract_email_domain, extract_website_domain
from services.email_validator import validate_email, pre_validate_result
from services.neverbounce_bulkupload_service import verify_email_list
from services.excel_writer import write_results_to_excel
from services.jwt_service import get_user_from_token
import os
import threading

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "../templates"))

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "../uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── NeverBounce result → requirements output label ────────────────────────────
NB_RESULT_MAP = {
    "valid":      "valid",
    "invalid":    "invalid",
    "catch-all":  "catch_all",
    "catchall":   "catch_all",
    "unknown":    "unknown",
    "disposable": "invalid",
}


# ─────────────────────────────────────────────────────────────────────────────
# Background verification worker
# ─────────────────────────────────────────────────────────────────────────────

def _run_verification(file_id: int, user_id: int, records: list, file_path: str):
    """
    records = list of {"email", "website", "company_name"}
    file_path = saved .xlsx path for write-back

    Requirements compliance:
      • Per-record try/except — one bad record never blocks others
      • DNS check disabled for bulk (performance: 20k records)
      • api_error result written to ValidationLog on any NeverBounce failure
      • Partial commit every 500 records — bulk failure never loses all work
    """
    db = SessionLocal()
    try:
        db_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if db_file:
            db_file.status = "processing"
            db.commit()

        all_results  = []
        log_objects  = []
        api_queue    = []
        seen         = set()
        log_by_email = {}

        print(f"[Pipeline] file_id={file_id} — {len(records)} records")

        for rec in records:
            try:
                email        = (rec.get("email") or "").strip().lower()
                website      = rec.get("website")
                company_name = rec.get("company_name")
                email_dom    = extract_email_domain(email) if email else None
                website_dom  = extract_website_domain(website)

                # ── Duplicate ─────────────────────────────────────────────────
                if email and email in seen:
                    log_objects.append(ValidationLog(
                        file_id=file_id, user_id=user_id,
                        email=email, company_name=company_name, website=website,
                        email_domain=email_dom, website_domain=website_dom,
                        step1_result=None, step1_passed=False,
                        pre_check_result=None, api_called=False, api_result=None,
                        final_status="Duplicate – Skipped", is_duplicate=True,
                    ))
                    continue

                # ── Empty email → Skipped – Missing Data ──────────────────────
                if not email:
                    log_objects.append(ValidationLog(
                        file_id=file_id, user_id=user_id,
                        email="", company_name=company_name, website=website,
                        email_domain=None, website_domain=website_dom,
                        step1_result="skipped_missing", step1_passed=False,
                        pre_check_result=None, api_called=False, api_result=None,
                        final_status="Skipped – Missing Data", is_duplicate=False,
                    ))
                    all_results.append(build_step1_skipped_result("", "skipped_missing"))
                    continue

                seen.add(email)

                # ── Step 1: Domain match ───────────────────────────────────────
                check        = check_domain(email, website)
                step1        = check.get("step1_result") or check.get("step1_status")
                step1_passed = check["proceed"]

                if not step1_passed:
                    final = "Skipped – Missing Data" if step1 == "skipped_missing" else "Domain Mismatch"
                    log_objects.append(ValidationLog(
                        file_id=file_id, user_id=user_id,
                        email=email, company_name=company_name, website=website,
                        email_domain=email_dom, website_domain=website_dom,
                        step1_result=step1, step1_passed=False,
                        pre_check_result=None, api_called=False, api_result=None,
                        final_status=final, is_duplicate=False,
                    ))
                    all_results.append(build_step1_skipped_result(email, step1))
                    print(f"[Step1] {email} → {step1}")
                    continue

                # ── Pre-validation — NO DNS for bulk (20k performance) ─────────
                is_valid, reason = validate_email(email, check_dns=False)
                if not is_valid:
                    result = pre_validate_result(email, reason)
                    result["step1_status"] = step1
                    all_results.append(result)
                    log_objects.append(ValidationLog(
                        file_id=file_id, user_id=user_id,
                        email=email, company_name=company_name, website=website,
                        email_domain=email_dom, website_domain=website_dom,
                        step1_result=step1, step1_passed=True,
                        pre_check_result=reason,
                        pre_check_reason=f"email-validator: {reason}",
                        api_called=False, api_result=None,
                        final_status="Invalid", is_duplicate=False,
                    ))
                    print(f"[PreValidate] {email} — {reason}")
                    continue

                # ── Queue for NeverBounce ─────────────────────────────────────
                api_queue.append(email)
                log_entry = ValidationLog(
                    file_id=file_id, user_id=user_id,
                    email=email, company_name=company_name, website=website,
                    email_domain=email_dom, website_domain=website_dom,
                    step1_result=step1, step1_passed=True,
                    pre_check_result="passed",
                    api_called=True, api_result=None,
                    final_status=None, is_duplicate=False,
                )
                log_objects.append(log_entry)
                log_by_email[email] = log_entry

            except Exception as rec_err:
                # Requirements: failed records must NOT block remaining records
                print(f"[Pipeline] per-record error ({email}): {rec_err}")
                log_objects.append(ValidationLog(
                    file_id=file_id, user_id=user_id,
                    email=email or "", company_name=None, website=None,
                    step1_result=None, step1_passed=False,
                    pre_check_result=None, api_called=False,
                    api_result="api_error", api_error_msg=str(rec_err),
                    final_status="API Error", is_duplicate=False,
                ))
                continue

        print(f"[Pipeline] file_id={file_id} — {len(api_queue)} → NeverBounce | {len(all_results)} resolved")

        # ── Step 2: NeverBounce ────────────────────────────────────────────────
        api_results = []
        if api_queue:
            try:
                api_results = verify_email_list(api_queue)
                for r in api_results:
                    raw    = r.get("result", "unknown")
                    mapped = NB_RESULT_MAP.get(raw.lower(), "unknown") if raw != "api_error" else "api_error"
                    r["result"]       = mapped
                    r["step1_status"] = "domain_match"

                    # Update ValidationLog entry for this email
                    le = log_by_email.get(r["email"])
                    if le:
                        le.api_result   = mapped
                        le.api_job_id   = r.get("job_id")
                        le.api_error_msg = r.get("api_error_msg")
                        le.final_status = {
                            "valid":     "Valid",
                            "invalid":   "Invalid",
                            "catch_all": "Catch-all",
                            "unknown":   "Unknown",
                            "api_error": "API Error",
                        }.get(mapped, mapped.replace("_", " ").title())

            except RuntimeError as e:
                if str(e) == "insufficient_credits":
                    print(f"[Pipeline] file_id={file_id} — 0 NeverBounce credits")
                    for em in api_queue:
                        le = log_by_email.get(em)
                        if le:
                            le.api_result    = "api_error"
                            le.api_error_msg = "Insufficient NeverBounce credits"
                            le.final_status  = "API Error"
                    if db_file:
                        db_file.status = "no_credits"
                        db.commit()
                    if not all_results:
                        # Still save logs before returning
                        if log_objects:
                            db.bulk_save_objects(log_objects)
                            db.commit()
                        return

        all_results.extend(api_results)

        # ── Bulk-save ValidationLog rows ───────────────────────────────────────
        if log_objects:
            db.bulk_save_objects(log_objects)

        print(f"[Pipeline] file_id={file_id} — total results: {len(all_results)}, logs: {len(log_objects)}")

        if not all_results:
            if db_file:
                db_file.status = "failed"
                db.commit()
            return

        # ── Save EmailVerification in chunks (partial commit — never lose all work)
        # Requirements: "Failed records must not block remaining records"
        CHUNK = 500
        saved = 0
        for i in range(0, len(all_results), CHUNK):
            chunk = [r for r in all_results[i:i+CHUNK] if r.get("email")]
            try:
                db.bulk_save_objects([
                    EmailVerification(
                        email=r["email"], user_id=user_id, file_id=file_id,
                        job_id=r.get("job_id"), status=r["status"], result=r["result"],
                        suggested_correction=r.get("suggested_correction"),
                        flags=r.get("flags"), address_info=r.get("address_info"),
                        execution_time=r.get("execution_time"),
                        credits_info=r.get("credits_info"),
                    )
                    for r in chunk
                ])
                db.commit()
                saved += len(chunk)
                print(f"[Pipeline] file_id={file_id} — saved chunk {i//CHUNK+1} ({saved}/{len(all_results)})")
            except Exception as chunk_err:
                print(f"[Pipeline] file_id={file_id} — chunk {i//CHUNK+1} save error: {chunk_err}")
                db.rollback()

        # Update EmailDetails
        for r in all_results:
            if r.get("email"):
                try:
                    db.query(EmailDetails).filter(
                        EmailDetails.email == r["email"],
                        EmailDetails.user_id == user_id
                    ).update({"status": r["result"]})
                except Exception:
                    pass

        if db_file and db_file.status != "no_credits":
            db_file.status = "complete"
            db_file.verified_count = saved
            db.commit()

        # ── Write results back to Excel ────────────────────────────────────────
        if file_path and file_path.lower().endswith((".xlsx", ".xls")):
            try:
                write_results_to_excel(file_path, all_results)
                print(f"[Pipeline] file_id={file_id} — Excel write-back done")
            except Exception as ex:
                print(f"[Pipeline] file_id={file_id} — Excel write-back failed: {ex}")

        # Summary log
        by_final = {}
        for lo in log_objects:
            k = lo.final_status or "pending"
            by_final[k] = by_final.get(k, 0) + 1
        print(f"[Pipeline] file_id={file_id} DONE — breakdown: {by_final}")

    except Exception as e:
        import traceback
        print(f"[Pipeline] file_id={file_id} ERROR: {e}")
        traceback.print_exc()
        db.rollback()
        try:
            f = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
            if f:
                f.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Lists Page
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/lists", response_class=HTMLResponse)
def lists_page(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    files = db.query(UploadedFile).filter(
        UploadedFile.user_id == user.id
    ).order_by(UploadedFile.created_at.desc()).all()

    file_stats = {}
    for f in files:
        rows = db.query(EmailVerification).filter(EmailVerification.file_id == f.id).all()
        stats = {
            "valid": 0, "invalid": 0, "unknown": 0, "catch_all": 0,
            "domain_mismatch": 0, "skipped_missing": 0, "disposable": 0,
            "total": len(rows), "job_id": None,
            "billable_emails": 0,   # step1_result == 'domain_match' from validation_logs
            "duplicate_count": 0,   # is_duplicate == True from validation_logs
        }
        for r in rows:
            res = r.result or ""
            if res in stats:
                stats[res] += 1
            if r.job_id and not stats["job_id"]:
                stats["job_id"] = r.job_id

        # Pull billable + duplicate counts from validation_logs
        try:
            logs = db.query(ValidationLog).filter(ValidationLog.file_id == f.id).all()
            stats["billable_emails"] = sum(
                1 for l in logs if l.step1_result == "domain_match"
            )
            stats["duplicate_count"] = sum(
                1 for l in logs if l.is_duplicate
            )
        except Exception:
            pass  # ValidationLog table may not exist yet on older deployments

        file_stats[f.id] = stats

    return templates.TemplateResponse("lists.html", {
        "request": request, "user": user,
        "files": files, "file_stats": file_stats, "active": "lists"
    })


# ─────────────────────────────────────────────────────────────────────────────
# Upload File
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/lists/upload")
async def upload_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ["csv", "xls", "xlsx"]:
        return JSONResponse({"error": "Only CSV or Excel files are allowed"}, status_code=400)

    content = await file.read()

    # Extract full records (email + website + company_name)
    records = extract_records_from_file(content, ext)

    if not records:
        return JSONResponse({"error": "No valid emails found in file"}, status_code=400)

    unique_emails = list({r["email"] for r in records if r.get("email")})

    # Save file to disk
    save_path = os.path.join(UPLOAD_DIR, f"{user.id}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(content)

    db_file = UploadedFile(
        user_id=user.id,
        file_name=file.filename,
        file_path=save_path,
        total_emails=len(unique_emails),
        status="pending"
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    db.bulk_save_objects([
        EmailDetails(email=e, status="pending", user_id=user.id)
        for e in unique_emails
    ])
    db.commit()

    # Fire background thread — pass full records + file path for write-back
    threading.Thread(
        target=_run_verification,
        args=(db_file.id, user.id, records, save_path),
        daemon=True
    ).start()

    return JSONResponse({
        "success":      True,
        "file_id":      db_file.id,
        "file_name":    file.filename,
        "emails_found": len(unique_emails),
        "status":       "pending",
        "message":      f"Processing {len(unique_emails)} emails in background."
    })


# ─────────────────────────────────────────────────────────────────────────────
# Poll status / Delete
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/lists/status/{file_id}")
def file_status(file_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    db_file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id, UploadedFile.user_id == user.id
    ).first()
    if not db_file:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return JSONResponse({
        "file_id":        db_file.id,
        "file_name":      db_file.file_name,
        "status":         getattr(db_file, "status", "unknown"),
        "total_emails":   db_file.total_emails,
        "verified_count": getattr(db_file, "verified_count", 0),
    })


@router.post("/lists/delete/{file_id}")
def delete_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_user_from_token(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    db_file = db.query(UploadedFile).filter(
        UploadedFile.id == file_id, UploadedFile.user_id == user.id
    ).first()
    if db_file:
        if os.path.exists(db_file.file_path):
            os.remove(db_file.file_path)
        db.delete(db_file)
        db.commit()
    return RedirectResponse(url="/lists", status_code=302)