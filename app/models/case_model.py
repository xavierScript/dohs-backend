from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
import uuid


def generate_case_id() -> str:
    return f"CASE-{uuid.uuid4().hex[:8].upper()}"

def generate_person_id() -> str:
    return f"PER-{uuid.uuid4().hex[:8].upper()}"


class BaseCase(SQLModel):
    case_id: str = Field(default_factory=generate_case_id, index=True)
    personID: str = Field(default_factory=generate_person_id, index=True)
    disease: str
    classification: str  # Suspected, Probable, Confirmed
    outcome: str = 'Alive'        # Alive, Dead, Unknown
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    state: str
    lga: str
    health_facility: str
    region: Optional[str] = None
    date_of_onset: Optional[datetime] = None
    date_of_confirmation: Optional[datetime] = None
    reporting_source: Optional[str] = None


# -------------------------
# HEALTH CASE MODEL
# -------------------------
class HealthCaseBase(BaseCase):
    age: Optional[int] = None
    sex: Optional[str] = None
    occupation: Optional[str] = None
    symptoms: Optional[str] = None
    risk_factors: Optional[str] = None
    category: str = Field(default="Human", const=True)


class HealthCase(HealthCaseBase, table=True):
    __tablename__ = "health_reports"
    id: Optional[int] = Field(default=None, primary_key=True)
    reported_at: datetime = Field(default_factory=datetime.utcnow)
    reporter_id: Optional[str] = Field(default=None, foreign_key="health_workers.id")


class HealthCaseCreate(HealthCaseBase):
    pass


class HealthCaseRead(HealthCaseBase):
    id: int
    reported_at: datetime


# -------------------------
# ANIMAL CASE MODEL
# -------------------------
class AnimalCaseBase(BaseCase):
    animal_species: str
    number_affected: Optional[int] = None
    symptoms: Optional[str] = None
    lab_results: Optional[str] = None
    category: str = Field(default="Animal", const=True)


class AnimalCase(AnimalCaseBase, table=True):
    __tablename__ = "animal_reports"
    id: Optional[int] = Field(default=None, primary_key=True)
    reported_at: datetime = Field(default_factory=datetime.utcnow)
    reporter_id: Optional[str] = Field(default=None, foreign_key="health_workers.id")


class AnimalCaseCreate(AnimalCaseBase):
    pass


class AnimalCaseRead(AnimalCaseBase):
    id: int
    reported_at: datetime


# -------------------------
# ENVIRONMENTAL CASE MODEL
# -------------------------
class EnvironmentalCaseBase(BaseCase):
    environmental_factors: str
    sample_collected: Optional[bool] = None
    lab_results: Optional[str] = None
    category: str = Field(default="Environmental", const=True)


class EnvironmentalCase(EnvironmentalCaseBase, table=True):
    __tablename__ = "environmental_reports"
    id: Optional[int] = Field(default=None, primary_key=True)
    reported_at: datetime = Field(default_factory=datetime.utcnow)
    reporter_id: Optional[str] = Field(default=None, foreign_key="health_workers.id")


class EnvironmentalCaseCreate(EnvironmentalCaseBase):
    pass


class EnvironmentalCaseRead(EnvironmentalCaseBase):
    id: int
    reported_at: datetime
