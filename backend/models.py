from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    username: str
    password: str


class TwoFARequest(BaseModel):
    code: str


class UnfollowRequest(BaseModel):
    user_pk: str
    username: str


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
