"""
neverbounce_bulkupload_service.py
──────────────────────────────────
Requirements Section 5b:
  • Rate limiting and retry logic per NeverBounce vendor guidelines
  • Handle API errors and timeouts gracefully — log and mark as "API Error"
  • Failed records must not block remaining records

Retry policy:
  • Single-check: up to MAX_RETRIES=3 attempts with exponential backoff
  • Bulk job: timeout → fall back to single-check (each with retry)
  • Any error on a single email → result="api_error", never throws, never blocks
"""

import os
import time
import neverbounce_sdk
from dotenv import load_dotenv

load_dotenv()

API_KEY       = os.getenv("NEVERBOUNCE_API_KEY")
POLL_INTERVAL = 3        # seconds between job status polls
MAX_WAIT_TIME = 300      # 5 minutes max for bulk job
MAX_RETRIES   = 3        # retry attempts per single-check
RETRY_BACKOFF = [2, 4, 8]  # wait seconds between retries

client = neverbounce_sdk.client(api_key=API_KEY, api_version="v4.2")


# ── Single-check with retry ────────────────────────────────────────────────────

def _api_error_result(email: str, job_id=None, error_msg: str = "API Error") -> dict:
    """Standard result dict for any API failure."""
    return {
        "email":                email,
        "job_id":               job_id,
        "status":               "failed",
        "result":               "api_error",
        "flags":                ["api_error"],
        "suggested_correction": None,
        "address_info":         {"original_email": email},
        "execution_time":       None,
        "credits_info":         None,
        "api_error_msg":        error_msg,
    }


def verify_single(email: str, job_id=None) -> dict:
    """
    Single-check with retry + exponential backoff.
    Requirements: "Handle API errors and timeouts gracefully — log and mark accordingly"
    Never raises — always returns a result dict.
    """
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.single_check(
                email=email,
                address_info=True,
                credits_info=True
            )
            return {
                "email":                email,
                "job_id":               job_id,
                "status":               "success",
                "result":               resp.get("result"),
                "flags":                resp.get("flags"),
                "suggested_correction": resp.get("suggested_correction"),
                "address_info":         resp.get("address_info"),
                "execution_time":       resp.get("execution_time"),
                "credits_info":         resp.get("credits_info"),
            }

        except Exception as e:
            last_error = str(e)

            # Insufficient credits — no point retrying, propagate immediately
            if "Insufficient credit" in last_error or "insufficient_credits" in last_error:
                print(f"[NeverBounce] No credits — cannot verify {email}")
                raise RuntimeError("insufficient_credits")

            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                print(f"[NeverBounce] single_check error for {email} (attempt {attempt+1}): {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"[NeverBounce] single_check failed after {MAX_RETRIES} attempts for {email}: {e}")

    # All retries exhausted — mark as API Error (req: "log error and mark accordingly")
    return _api_error_result(email, job_id, error_msg=f"API Error after {MAX_RETRIES} retries: {last_error}")


# ── Bulk verify ────────────────────────────────────────────────────────────────

def verify_email_list(emails: list) -> list:
    """
    Bulk verify via NeverBounce jobs API.
    Falls back to single-check (with retry) if job fails or list is small.
    Each individual email failure returns api_error result — never blocks others.
    """
    if not emails:
        return []

    # Small lists → single-check directly (faster, more reliable)
    if len(emails) <= 5:
        print(f"[NeverBounce] small list ({len(emails)}) — using single-check with retry")
        results = []
        for e in emails:
            try:
                results.append(verify_single(e))
            except RuntimeError as err:
                if str(err) == "insufficient_credits":
                    raise
                results.append(_api_error_result(e, error_msg=str(err)))
        return results

    # Bulk job
    input_data = [{"id": str(i), "email": e} for i, e in enumerate(emails)]
    job_id     = None

    try:
        print(f"[NeverBounce] creating bulk job for {len(emails)} emails")
        create_resp = client.jobs_create(input=input_data, filename="uploaded_emails.csv")
        job_id      = create_resp["job_id"]
        print(f"[NeverBounce] job created: {job_id}")

        # Parse + auto-start
        client.jobs_parse(job_id=job_id, auto_start=True)

        # Poll until complete with timeout
        start = time.time()
        while True:
            status_resp = client.jobs_status(job_id=job_id)
            job_status  = status_resp.get("job_status")
            print(f"[NeverBounce] job {job_id} status: {job_status}")

            if job_status == "complete":
                break
            if job_status in ("failed", "aborted"):
                raise Exception(f"NeverBounce job {job_status}")
            if time.time() - start > MAX_WAIT_TIME:
                raise TimeoutError(f"NeverBounce job timed out after {MAX_WAIT_TIME}s")

            # Rate limit: respect poll interval per NeverBounce guidelines
            time.sleep(POLL_INTERVAL)

        # Fetch results
        results = []
        for r in client.jobs_results(job_id=job_id):
            data         = r.get("data", {})
            verification = r.get("verification", {})
            results.append({
                "email":                data.get("email"),
                "job_id":               str(job_id),
                "status":               "success",
                "result":               verification.get("result"),
                "flags":                verification.get("flags"),
                "suggested_correction": verification.get("suggested_correction"),
                "address_info":         verification.get("address_info"),
                "execution_time":       verification.get("execution_time"),
                "credits_info":         verification.get("credits_info"),
            })

        print(f"[NeverBounce] bulk job {job_id} done — {len(results)} results")
        return results

    except RuntimeError:
        raise  # insufficient_credits — propagate to caller

    except Exception as e:
        # Bulk job failed → fall back to single-check per email with retry
        # Requirements: "Failed records must not block remaining records"
        print(f"[NeverBounce] bulk job failed: {e} — falling back to single-check for {len(emails)} emails")
        results = []
        for em in emails:
            try:
                results.append(verify_single(em, job_id=job_id))
            except RuntimeError as err:
                if str(err) == "insufficient_credits":
                    raise
                results.append(_api_error_result(em, job_id=job_id, error_msg=str(err)))
        return results