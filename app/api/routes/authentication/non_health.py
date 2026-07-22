import re
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.params import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm, OAuth2PasswordBearer, APIKeyHeader
from sqlmodel import Session, select
from passlib.hash import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional

from schemas.user import ChangePassword, LoginRequest, PerformReset, ResetRequest, UpdateProfile
from models.workers_model import NonHealthWorkerCreate, NonHealthWorker
from core.db import get_session
from core.security import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = 60

router = APIRouter(prefix="/non-health", tags=["NonHealthWorker Authentication"])
api_key_scheme = APIKeyHeader(name="Authorization", scheme_name="Bearer")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@router.post("/signup")
def register(user: NonHealthWorkerCreate, session: Session = Depends(get_session)):
    try:
        # Optional: Validate email format if not already done in schema
        if not re.match(r"[^@]+@[^@]+\.[^@]+", user.email):
            raise HTTPException(status_code=422, detail="Invalid email format")

        existing_user = session.exec(
            select(NonHealthWorker).where(NonHealthWorker.email == user.email)
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

        hashed_password = bcrypt.hash(user.password)

        new_user = NonHealthWorker(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone_number=user.phone_number,
            location=user.location,
            password=hashed_password
        )

        session.add(new_user)
        session.commit()
        session.refresh(new_user)

        return {
            "message": "Registration successful",
            "user_id": new_user.id
        }

 

    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )
    

@router.post("/login")
def login(
    login_data: LoginRequest,
    session: Session = Depends(get_session)
):
    try:
        user = session.exec(
            select(NonHealthWorker).where(NonHealthWorker.email == login_data.email)
        ).first()

        if not user or not bcrypt.verify(login_data.password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        access_token = create_access_token(data={"sub": str(user.id)})

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "location": user.location
            }
        }

 

    except Exception as e:
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error occurred: {str(e)}"
        )
    






bearer_scheme = HTTPBearer()  

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: Session = Depends(get_session)
):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    user = session.exec(
        select(NonHealthWorker).where(NonHealthWorker.id == user_id)
    ).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return user


@router.get("/me")
def get_profile(current_user: NonHealthWorker = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "email": current_user.email,
        "location": current_user.location,
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
    user = session.exec(select(NonHealthWorker).where(NonHealthWorker.email == data.email)).first()
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
    user = session.get(NonHealthWorker, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password = bcrypt.hash(data.new_password)
    session.add(user)
    session.commit()
    return {"message": "Password reset successful"}

# === Delete Account ===
@router.delete("/me")
def delete_account(current_user: NonHealthWorker = Depends(get_current_user), session: Session = Depends(get_session)):
    session.delete(current_user)
    session.commit()
    return {"message": "Account deleted successfully"}

# === Change Password ===
@router.post("/change-password")
def change_password(data: ChangePassword, current_user: NonHealthWorker = Depends(get_current_user), session: Session = Depends(get_session)):
    if not bcrypt.verify(data.old_password, current_user.password):
        raise HTTPException(status_code=400, detail="Incorrect old password")
    current_user.password = bcrypt.hash(data.new_password)
    session.add(current_user)
    session.commit()
    return {"message": "Password changed successfully"}


# == Update Profile ===
@router.patch("/me")
def update_profile(update: UpdateProfile, current_user: NonHealthWorker = Depends(get_current_user), session: Session = Depends(get_session)):
    for field, value in update.dict(exclude_none=True).items():
        setattr(current_user, field, value)
    session.add(current_user)
    session.commit()
    return {"message": "Profile updated successfully"}

