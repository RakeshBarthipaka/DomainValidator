import os
import time
import neverbounce_sdk
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("NEVERBOUNCE_API_KEY")

client = neverbounce_sdk.client(
    api_key=API_KEY,
    api_version="v4.2"
)

POLL_INTERVAL = 3
MAX_WAIT_TIME = 300


def verify_single(email: str, job_id: int = None) -> dict:
    """Single-check fallback using the single verify endpoint."""
    try:
        resp = client.single_check(
            email=email,
            address_info=True,
            credits_info=True
        )
        return {
            "email":                email,
            "job_id":               job_id,       # int or None — never a string
            "status":               "success",
            "result":               resp.get("result"),
            "flags":                resp.get("flags"),
            "suggested_correction": resp.get("suggested_correction"),
            "address_info":         resp.get("address_info"),
            "execution_time":       resp.get("execution_time"),
            "credits_info":         resp.get("credits_info"),
        }
    except Exception as e:
        err = str(e)
        if "Insufficient credit" in err:
            print(f"[NeverBounce] ⚠ No credits — cannot verify {email}")
            raise RuntimeError("insufficient_credits")
        print(f"[NeverBounce] single_check error for {email}: {e}")
        return {
            "email":  email, "job_id": job_id, "status": "failed", "result": "unknown",
            "flags": [], "suggested_correction": None,
            "address_info": None, "execution_time": None, "credits_info": None,
        }


def verify_email_list(emails: list) -> list:
    """
    Bulk verify via NeverBounce jobs API.
    Falls back to single-check per email if the job fails or list is small.
    """
    if not emails:
        return []

    # For very small lists (≤5), single-check is faster and more reliable
    if len(emails) <= 5:
        print(f"[NeverBounce] small list ({len(emails)}) — using single-check")
        results = []
        for e in emails:
            try:
                results.append(verify_single(e))
            except RuntimeError as err:
                if str(err) == "insufficient_credits":
                    print("[NeverBounce] ⚠ Stopping — account has 0 credits")
                    raise
                results.append({
                    "email": e, "job_id": None, "status": "failed", "result": "unknown",
                    "flags": [], "suggested_correction": None,
                    "address_info": None, "execution_time": None, "credits_info": None,
                })
        return results

    input_data = [{"id": str(i), "email": e} for i, e in enumerate(emails)]

    try:
        # 1. Create job
        print(f"[NeverBounce] creating bulk job for {len(emails)} emails")
        create_resp = client.jobs_create(
            input=input_data,
            filename="uploaded_emails.csv"
        )
        print(f"[NeverBounce] create response: {create_resp}")
        job_id = create_resp["job_id"]

        # 2. Parse
        parse_resp = client.jobs_parse(job_id=job_id, auto_start=True)
        print(f"[NeverBounce] parse response: {parse_resp}")

        # 3. Poll until complete
        start_time = time.time()
        while True:
            status_resp = client.jobs_status(job_id=job_id)
            job_status  = status_resp.get("job_status")
            print(f"[NeverBounce] job {job_id} status: {job_status} | full: {status_resp}")

            if job_status == "complete":
                break
            if job_status in ["failed", "aborted"]:
                raise Exception(f"NeverBounce job {job_status} — falling back to single-check")
            if time.time() - start_time > MAX_WAIT_TIME:
                raise TimeoutError(f"NeverBounce job timed out after {MAX_WAIT_TIME}s")

            time.sleep(POLL_INTERVAL)

        # 4. Fetch results
        verified_results = []
        for r in client.jobs_results(job_id=job_id):
            data         = r.get("data", {})
            verification = r.get("verification", {})
            verified_results.append({
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

        print(f"[NeverBounce] bulk job {job_id} complete — {len(verified_results)} results")
        return verified_results

    except Exception as e:
        print(f"[NeverBounce] bulk job failed: {e} — falling back to single-check for {len(emails)} emails")
        return [verify_single(e) for e in emails]