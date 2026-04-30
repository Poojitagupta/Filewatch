from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    token: str
    user: UserOut


class DirectoryCreate(BaseModel):
    path: str
    label: Optional[str] = None


class DirectoryOut(BaseModel):
    id: str
    path: str
    label: Optional[str]
    status: str
    file_count: int
    alert_count: int
    last_scan: Optional[datetime]
    created_at: datetime


class EventOut(BaseModel):
    id: str
    event_type: str
    file_path: str
    severity: str
    message: str
    old_hash: Optional[str]
    new_hash: Optional[str]
    directory_path: Optional[str]
    created_at: datetime


class StatsOut(BaseModel):
    directories: int
    files_tracked: int
    alerts_today: int
    last_scan: Optional[datetime]