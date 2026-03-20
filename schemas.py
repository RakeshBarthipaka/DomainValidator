from pydantic import BaseModel
from typing import List


class EmailRequest(BaseModel):
    emails: List[str]


class EmailResponse(BaseModel):
    email: str
    status: str
    result: str


class UserCreate(BaseModel):
    name: str
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str