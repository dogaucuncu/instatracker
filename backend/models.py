import re
from pydantic import BaseModel, field_validator
from typing import Optional


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Kullanıcı adı boş olamaz.")
        if len(v) > 30:
            raise ValueError("Kullanıcı adı çok uzun.")
        # Instagram usernames: letters, numbers, underscores, dots only
        if not re.match(r'^[a-zA-Z0-9._]+$', v):
            raise ValueError("Geçersiz kullanıcı adı formatı.")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v:
            raise ValueError("Şifre boş olamaz.")
        if len(v) > 128:
            raise ValueError("Şifre çok uzun.")
        return v


class TwoFARequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r'^[0-9]{4,8}$', v):
            raise ValueError("Doğrulama kodu sadece 4-8 haneli rakam olmalıdır.")
        return v


class UnfollowRequest(BaseModel):
    user_pk: str
    username: str

    @field_validator("user_pk")
    @classmethod
    def validate_user_pk(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r'^[0-9]+$', v):
            raise ValueError("user_pk sadece rakamlardan oluşmalıdır.")
        if len(v) > 20:
            raise ValueError("user_pk çok uzun.")
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 30:
            raise ValueError("Kullanıcı adı çok uzun.")
        return v


class AccountInfo(BaseModel):
    pk: str
    username: str
    full_name: Optional[str] = None
    profile_pic_url: Optional[str] = None


class EventOut(BaseModel):
    id: int
    user_pk: str
    username: str
    full_name: Optional[str] = None
    profile_pic_url: Optional[str] = None
    event_type: str
    still_following: bool
    detected_at: str
    details: Optional[dict] = None


class ScanResult(BaseModel):
    scan_id: int
    status: str
    new_followers: int
    lost_followers: int
    events_created: int
    message: str


class DashboardStats(BaseModel):
    total_events: int
    unfollowed: int
    blocked: int
    deactivated: int
    new_followers: int
    still_following_count: int
    follower_count: int
    following_count: int
    total_scans: int
    last_scan: Optional[str] = None


class ScanHistoryItem(BaseModel):
    id: int
    started_at: str
    completed_at: Optional[str] = None
    status: str
    new_followers: int
    lost_followers: int
    error_message: Optional[str] = None
