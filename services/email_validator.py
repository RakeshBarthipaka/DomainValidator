"""
Middle-layer email validation using the `email-validator` library.
Runs BEFORE NeverBounce — invalid emails are rejected with zero credits used.

Install: pip install email-validator
"""

from email_validator import validate_email as _validate, EmailNotValidError


def validate_email(email: str) -> tuple[bool, str | None]:
    """
    Returns (should_proceed_to_api: bool, skip_reason: str | None)

    True  → email passed basic checks, send to NeverBounce
    False → email is invalid, skip API entirely
    """
    try:
        result = _validate(email.strip(), check_deliverability=True)
        # Normalize to canonical form (e.g. lowercased, unicode normalized)
        return True, None
    except EmailNotValidError as e:
        reason = str(e).lower()
        if "disposable" in reason:
            return False, "disposable"
        return False, "invalid"


def pre_validate_result(email: str, reason: str) -> dict:
    """Build a result dict for emails that failed pre-validation."""
    domain = email.split("@")[1] if "@" in email else ""
    result_map = {"disposable": "disposable", "invalid": "invalid"}
    return {
        "email":                email.strip().lower(),
        "job_id":               None,
        "status":               "success",
        "result":               result_map.get(reason, "invalid"),
        "flags":                [f"pre_validation_{reason}"],
        "suggested_correction": None,
        "address_info":         {"original_email": email.strip().lower(), "domain": domain},
        "execution_time":       0,
        "credits_info":         None,
        "pre_validated":        True,
        "skip_reason":          reason,
    }