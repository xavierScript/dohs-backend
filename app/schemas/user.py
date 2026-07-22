from typing import Optional
from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None

    class Config:
        orm_mode = True

class NonHealthWorkerCreate(BaseModel):
    user_id: int
    non_health_worker_type: str
    non_health_worker_subtype: str
    non_health_worker_subtype_other: str | None = None


class HealthWorkerLogin(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ResetRequest(BaseModel):
    email: EmailStr

class PerformReset(BaseModel):
    token: str
    new_password: str

class UpdateProfile(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    location: Optional[str] = None

class ChangePassword(BaseModel):
    old_password: str
    new_password: str


class UpdateUserLocationDetails(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    facility: Optional[str] = None
    state: Optional[str] = None
    lga: Optional[str] = None