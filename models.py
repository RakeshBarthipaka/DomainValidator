from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey
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
    status         = Column(String, default="pending")   # pending / processing / complete / failed
    verified_count = Column(Integer, default=0)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    user          = relationship("User", back_populates="files")
    verifications = relationship("EmailVerification", back_populates="file", cascade="all, delete")


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
    job_id               = Column(String, index=True, nullable=True)   # NeverBounce job id (VARCHAR)
    status               = Column(String)
    result               = Column(String)
    suggested_correction = Column(String)
    flags                = Column(JSON)
    address_info         = Column(JSON)
    credits_info         = Column(JSON)
    execution_time       = Column(Integer)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())

    file = relationship("UploadedFile", back_populates="verifications")