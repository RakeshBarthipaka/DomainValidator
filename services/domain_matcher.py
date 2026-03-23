"""
domain_matcher.py
─────────────────
Requirements Section 5a — Step 1: Domain Matching Validation

Rules:
  1. Extract domain from Email  (part after @)
  2. Extract domain from Website (strip http/https, www, paths)
  3. Case-insensitive compare
  4. MATCH    → proceed to NeverBounce
  5. MISMATCH → store as "Domain Mismatch", skip NeverBounce
  6. Either field empty → "Skipped – Missing Data"

Output status values (per Section 5b):
  "domain_mismatch"  — email domain ≠ website domain
  "skipped_missing"  — email or website is empty
  "valid"            — NeverBounce: deliverable
  "invalid"          — NeverBounce: undeliverable
  "catch_all"        — NeverBounce: domain accepts all
  "unknown"          — NeverBounce: inconclusive
  "api_error"        — NeverBounce call errored
"""

import re


def extract_email_domain(email: str) -> str | None:
    try:
        return email.strip().lower().split("@")[1]
    except (IndexError, AttributeError):
        return None


def extract_website_domain(website: str | None) -> str | None:
    if not website:
        return None
    d = str(website).strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0].strip()
    return d or None


def domains_match(email_domain: str | None, website_domain: str | None) -> bool:
    """
    Exact match OR subdomain match.
    Examples:
      hocrox.com       == hocrox.com          → True
      app.dataflow.io  subdomain dataflow.io   → True
      nexgensolutions.com vs nexgen.com        → False
    """
    if not email_domain or not website_domain:
        return False
    e = email_domain.lower().strip()
    w = website_domain.lower().strip()
    return e == w or e.endswith("." + w) or w.endswith("." + e)


def check_domain(email: str, website: str | None) -> dict:
    """
    Run Step 1.
    Returns:
      {
        "proceed":        bool,
        "step1_status":   "domain_match" | "domain_mismatch" | "skipped_missing",
        "email_domain":   str | None,
        "website_domain": str | None,
      }
    """
    email_domain   = extract_email_domain(email)
    website_domain = extract_website_domain(website)

    # Missing data
    if not email or not website:
        return {
            "proceed": False,
            "step1_status": "skipped_missing",
            "email_domain": email_domain,
            "website_domain": website_domain,
        }

    if domains_match(email_domain, website_domain):
        return {
            "proceed": True,
            "step1_status": "domain_match",
            "email_domain": email_domain,
            "website_domain": website_domain,
        }

    return {
        "proceed": False,
        "step1_status": "domain_mismatch",
        "email_domain": email_domain,
        "website_domain": website_domain,
    }


def build_step1_skipped_result(email: str, step1_status: str) -> dict:
    """
    Result dict for records skipped at Step 1.
    These go to DB + Excel output column; NeverBounce is never called.
    """
    result_map = {
        "domain_mismatch": "domain_mismatch",
        "skipped_missing": "skipped_missing",
    }
    return {
        "email":                email,
        "job_id":               None,
        "status":               "skipped",
        "result":               result_map.get(step1_status, "skipped_missing"),
        "flags":                [step1_status],
        "suggested_correction": None,
        "address_info":         {"original_email": email},
        "execution_time":       0,
        "credits_info":         None,
        "step1_status":         step1_status,
    }