import uuid

from pydantic import EmailStr
from sqlmodel import Field, Relationship, SQLModel
from typing import Optional
from .base import Base




#NON HEALTH WORKER SCHEMA
class NonHealthWorker(Base, table=True):
    __tablename__ = "non_health_workers"
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    first_name: str
    last_name: str
    email: str
    phone_number: str
    location: str
    password: str 


class NonHealthWorkerCreate(Base):
    first_name: str
    last_name: str
    email: str
    phone_number: str
    location: str
    password: str


class NonHealthWorkerRead(Base):
    id: str
    name: str
    email: str
    phone_number: str
    location: str


#HEALTH WORKER SCHEMA
class HealthWorker(Base, table=True):
    __tablename__ = "health_workers"
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    first_name: str
    last_name: str
    email: str
    phone_number: str
    designation: str
    license_number: str
    location: str
    password: str
    facility: Optional[str] = Field(default='Unknown')
    state: Optional[str] = Field(default='Unknown')
    lga: Optional[str] = Field(default='Unknown')
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class HealthWorkerCreate(Base):
    first_name: str
    last_name: str
    email: str
    phone_number: str
    designation: str
    license_number: str
    location: str
    password: str


class HealthWorkerRead(SQLModel):
    id: str
    name: str
    email: str
    phone_number: str
    designation: str
    license_number: str
    location: str

class UsersRead(Base):
    token: str
