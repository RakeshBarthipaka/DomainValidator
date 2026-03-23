from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String)
    email      = Column(String, unique=True, index=True)
    password   = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    emails = relationship("EmailDetails", back_populates="user", cascade="all, delete")
    files  = relationship("UploadedFile", back_populates="user", cascade="all, delete")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id"))
    file_name      = Column(String)
    file_path      = Column(String)
    total_emails   = Column(Integer, default=0)
    status         = Column(String, default="pending")
    verified_count = Column(Integer, default=0)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    user            = relationship("User", back_populates="files")
    verifications   = relationship("EmailVerification", back_populates="file", cascade="all, delete")
    validation_logs = relationship("ValidationLog", back_populates="file", cascade="all, delete")


class EmailDetails(Base):
    __tablename__ = "email_details"

    id         = Column(Integer, primary_key=True, index=True)
    email      = Column(String)
    status     = Column(String)
    user_id    = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="emails")


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id                   = Column(Integer, primary_key=True, index=True)
    email                = Column(String)
    user_id              = Column(Integer, ForeignKey("users.id"), nullable=True)
    file_id              = Column(Integer, ForeignKey("uploaded_files.id"), nullable=True)
    job_id               = Column(String, index=True, nullable=True)
    status               = Column(String)
    result               = Column(String)
    suggested_correction = Column(String)
    flags                = Column(JSON)
    address_info         = Column(JSON)
    credits_info         = Column(JSON)
    execution_time       = Column(Integer)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())

    file = relationship("UploadedFile", back_populates="verifications")


class ValidationLog(Base):
    """
    Auto-created by SQLAlchemy via Base.metadata.create_all() in main.py.
    No manual SQL migration needed — table is created on app startup.

    Tracks every email record through all 3 pipeline steps:
      Step 1  — Domain match   (Col H email domain vs Col AF website domain)
      Pre     — Format + DNS   (email-validator library, between Step 1 and 2)
      Step 2  — NeverBounce    (only called when Step 1 + Pre both pass)
    """
    __tablename__ = "validation_logs"

    id           = Column(Integer, primary_key=True, index=True)
    file_id      = Column(Integer, ForeignKey("uploaded_files.id"), nullable=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=True)

    # ── Input (from Apollo columns F / H / AF) ─────────────────────────────────
    email        = Column(String, nullable=False, index=True)
    company_name = Column(String, nullable=True)   # Col F
    website      = Column(String, nullable=True)   # Col AF (raw value)

    # ── Step 1: Domain match ───────────────────────────────────────────────────
    email_domain   = Column(String, nullable=True)   # part after @ in email
    website_domain = Column(String, nullable=True)   # cleaned bare domain from URL
    step1_result   = Column(String, nullable=True, index=True)
    # domain_match | domain_mismatch | skipped_missing
    step1_passed   = Column(Boolean, default=False)  # True → advanced to pre-check

    # ── Pre-validation (format + DNS check) ────────────────────────────────────
    pre_check_result = Column(String, nullable=True)  # passed | invalid | disposable
    pre_check_reason = Column(String, nullable=True)  # reason text if failed

    # ── Step 2: NeverBounce API ────────────────────────────────────────────────
    api_called    = Column(Boolean, default=False)    # True → NeverBounce was called
    api_result    = Column(String, nullable=True, index=True)
    # valid | invalid | catch_all | unknown | api_error
    api_job_id    = Column(String, nullable=True)
    api_error_msg = Column(String, nullable=True)     # populated on API error/timeout

    # ── Final outcome written to Excel output column ───────────────────────────
    # Domain Mismatch | Skipped – Missing Data | Valid | Invalid |
    # Catch-all | Unknown | API Error | Duplicate – Skipped
    final_status  = Column(String, nullable=True, index=True)

    is_duplicate  = Column(Boolean, default=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    file = relationship("UploadedFile", back_populates="validation_logs")