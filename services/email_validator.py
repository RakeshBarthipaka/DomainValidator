"""
email_validator.py
──────────────────
Pre-validates email format before sending to NeverBounce.

IMPORTANT for bulk (20k records):
  check_deliverability=False  — skips DNS lookup per email.
  DNS lookup per email in a 20k loop would take hours.
  NeverBounce handles deliverability at the API level.

For single-check (/api/verify), DNS check is enabled because
the user is checking one email at a time interactively.
"""

from email_validator import validate_email as _validate, EmailNotValidError


def validate_email(email: str, check_dns: bool = False) -> tuple[bool, str | None]:
    """
    Returns (is_valid, reason_or_none).
    check_dns=False for bulk (performance), True for single interactive check.
    """
    try:
        _validate(email, check_deliverability=check_dns)
        return True, None
    except EmailNotValidError as e:
        return False, str(e)


def pre_validate_result(email: str, reason: str) -> dict:
    """Build a result dict for emails that failed pre-validation."""
    return {
        "email":                email,
        "job_id":               None,
        "status":               "failed",
        "result":               "invalid",
        "flags":                ["pre_validation_failed"],
        "suggested_correction": None,
        "address_info":         {"original_email": email},
        "execution_time":       0,
        "credits_info":         None,
        "pre_validated":        True,
        "skip_reason":          reason,
    }