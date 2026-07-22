from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select
from passlib.hash import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional

from schemas.user import ChangePassword, HealthWorkerLogin, PerformReset, ResetRequest, UpdateProfile, UpdateUserLocationDetails
from models.workers_model import HealthWorker, HealthWorkerCreate
from core.db import get_session
from core.security import settings
from pydantic import BaseModel, EmailStr

# === Settings ===
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = 60

router = APIRouter(prefix="/health", tags=["HealthWorker Authentication"])
auth_scheme = HTTPBearer()

# === Token Utilities ===
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(auth_scheme),
    session: Session = Depends(get_session)
) -> HealthWorker:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = session.get(HealthWorker, user_id)
    if user is None:
        raise credentials_exception
    return user

# === ROUTES ===

# === Signup ===
@router.post("/signup")
def register(user: HealthWorkerCreate, session: Session = Depends(get_session)):
    existing_user = session.exec(select(HealthWorker).where(HealthWorker.email == user.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = bcrypt.hash(user.password)
    new_user = HealthWorker(
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        phone_number=user.phone_number,
        license_number=user.license_number,
        designation=user.designation,
        location=user.location,
        password=hashed_password
    )
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    return {"message": "Registration successful", "user_id": new_user.id}

# === Login ===
@router.post("/login")
def login(data: HealthWorkerLogin, session: Session = Depends(get_session)):
    user = session.exec(select(HealthWorker).where(HealthWorker.email == data.email)).first()
    if not user or not bcrypt.verify(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    token = create_access_token(data={"sub": str(user.id)})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "designation": user.designation,
            "location": user.location
        }
    }

# === Auth Middleware ===

# === Get Profile ===
@router.get("/me")
def read_profile(current_user: HealthWorker = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": f"{current_user.first_name} {current_user.last_name}",
        "email": current_user.email,
        "phone_number": current_user.phone_number,
        "designation": current_user.designation,
        "location": current_user.location,
        "facility": current_user.facility,
        "state": current_user.state,
        "lga": current_user.lga,
        "latitude": current_user.latitude,
        "longitude": current_user.longitude

    }


# === Refresh Token ===
@router.post("/refresh")
def refresh_token(request: Request):
    refresh_token = request.headers.get("Authorization")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    token = refresh_token.split(" ")[-1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user_id = payload.get("sub")
    new_access_token = create_access_token({"sub": user_id})
    return {"access_token": new_access_token, "token_type": "bearer"}


# === Forgot Password ===
def forgot_password(data: ResetRequest, session: Session = Depends(get_session)):
    user = session.exec(select(HealthWorker).where(HealthWorker.email == data.email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")
    reset_token = create_access_token({"sub": str(user.id)}, timedelta(minutes=30))
    # TODO: Send reset_token via email in real app
    return {"reset_token": reset_token}

# === Reset Password ===
@router.post("/reset-password")
def reset_password(data: PerformReset, session: Session = Depends(get_session)):
    try:
        payload = jwt.decode(data.token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired reset token")
    user = session.get(HealthWorker, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password = bcrypt.hash(data.new_password)
    session.add(user)
    session.commit()
    return {"message": "Password reset successful"}

# === Delete Account ===
@router.delete("/me")
def delete_account(current_user: HealthWorker = Depends(get_current_user), session: Session = Depends(get_session)):
    session.delete(current_user)
    session.commit()
    return {"message": "Account deleted successfully"}

# === Change Password ===
@router.post("/change-password")
def change_password(data: ChangePassword, current_user: HealthWorker = Depends(get_current_user), session: Session = Depends(get_session)):
    if not bcrypt.verify(data.old_password, current_user.password):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    current_user.password = bcrypt.hash(data.new_password)
    session.add(current_user)
    session.commit()
    return {"message": "Password changed successfully"}


# == Update Profile ===
@router.patch("/me")
def update_profile(update: UpdateProfile, current_user: HealthWorker = Depends(get_current_user), session: Session = Depends(get_session)):
    for field, value in update.dict(exclude_none=True).items():
        setattr(current_user, field, value)
    session.add(current_user)
    session.commit()
    return {"message": "Profile updated successfully"}


# == Update Location ===
@router.patch("/location")
def update_users_location_details(update: UpdateUserLocationDetails, current_user: HealthWorker = Depends(get_current_user), session: Session = Depends(get_session)):
    for field, value in update.dict(exclude_none=True).items():
        setattr(current_user, field, value)
    session.add(current_user)
    session.commit()
    return {"message": "Profile location Updated successfully"}


