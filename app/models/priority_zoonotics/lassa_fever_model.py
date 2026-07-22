from sqlmodel import SQLModel, Field
from typing import Optional, List
from datetime import datetime
import uuid
from enum import Enum


def generate_case_id() -> str:
    return f"CASE-{uuid.uuid4().hex[:8].upper()}"

def generate_patient_id() -> str:
    return f"PAT-{uuid.uuid4().hex[:8].upper()}"


# Enums for better data validation
class Sex(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"

class PregnancyStatus(str, Enum):
    NOT_PREGNANT = "Not Pregnant"
    PREGNANT = "Pregnant"
    UNKNOWN = "Unknown"

class YesNoUnknown(str, Enum):
    YES = "Yes"
    NO = "No"
    UNKNOWN = "Unknown"

class Classification(str, Enum):
    SUSPECTED = "Suspected"
    PROBABLE = "Probable"
    CONFIRMED = "Confirmed"

class Outcome(str, Enum):
    ALIVE = "Alive"
    DEAD = "Dead"
    UNKNOWN = "Unknown"

class FacilityType(str, Enum):
    PRIMARY = "Primary"
    SECONDARY = "Secondary"
    TERTIARY = "Tertiary"
    TREATMENT_CENTRE = "Treatment Centre"

class PCRResult(str, Enum):
    POSITIVE = "Positive"
    NEGATIVE = "Negative"
    PENDING = "Pending"

class IsolationStatus(str, Enum):
    ISOLATED_LF_CENTRE = "Isolated in LF Centre"
    ISOLATED_HOLDING_AREA = "Isolated in Holding Area"
    NOT_ISOLATED = "Not Isolated"


class LassaFeverCase(SQLModel):
    patient_id: str = Field(default_factory=generate_patient_id, index=True)
    age: int = Field(..., ge=0, le=120, description="Patient age in years")
    sex: Sex
    pregnancy_status: Optional[PregnancyStatus] = None
    gestational_age: Optional[int] = Field(None, ge=0, le=45, description="Gestational age in weeks")
    state_of_residence: str
    lga_local_government_area: str
    date_of_report: datetime = Field(default_factory=datetime.now)
    reporting_facility_name: str
    reporting_facility_type: FacilityType

    # LOCATION INFORMATION
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    
    # B. Exposure History & One Health Linkages
    history_of_contact_with_rodents: YesNoUnknown
    history_of_consumption_or_handling_of_rats: YesNoUnknown
    travel_history_to_endemic_area: YesNoUnknown
    travel_history_location: Optional[str] = None
    travel_history_date: Optional[datetime] = None
    contact_with_confirmed_probable_case: YesNoUnknown
    contact_relationship: Optional[str] = None
    date_of_last_contact: Optional[datetime] = None
    participation_in_burial_rites: YesNoUnknown
    occupation: Optional[str] = None
    
    # C. Clinical Presentation & Case Definition
    date_of_onset_of_symptoms: Optional[datetime] = None
    fever: bool = False
    vomiting: bool = False
    diarrhea: bool = False
    sore_throat: bool = False
    myalgia: bool = False
    generalized_body_weakness: bool = False
    abdominal_pain: bool = False
    cough: bool = False
    retrosternal_pain: bool = False
    hearing_loss: bool = False
    facial_or_neck_swelling: bool = False
    abnormal_bleeding: YesNoUnknown
    bleeding_specification: Optional[str] = None
    response_to_anti_malarial_antibiotics: Optional[str] = None  # Yes/No/Partial
    
    # D. Clinical Examination & Triage Classification
    case_classification: Classification
    systolic_bp: Optional[int] = Field(None, ge=0, description="Systolic BP in mmHg")
    pulse_rate: Optional[int] = Field(None, ge=0, description="Pulse rate per minute")
    respiratory_rate: Optional[int] = Field(None, ge=0, description="Respiratory rate per minute")
    temperature: Optional[float] = Field(None, ge=30.0, le=45.0, description="Temperature in °C")
    spo2: Optional[int] = Field(None, ge=0, le=100, description="Oxygen saturation percentage")
    complications_present: YesNoUnknown
    complications_list: Optional[str] = None
    
    
    # E. Laboratory Investigations
    lassa_fever_rt_pcr_result: Optional[PCRResult] = None
    lassa_fever_rdt_result: Optional[PCRResult] = None
    date_of_sample_collection: Optional[datetime] = None
    date_of_result: Optional[datetime] = None
    platelet_count: Optional[int] = Field(None, ge=0, description="Platelet count in cells/ml³")
    ast_alt_elevated: YesNoUnknown
    creatinine_elevated: YesNoUnknown
    urea_elevated: YesNoUnknown
    proteinuria_hematuria: YesNoUnknown
    malaria_test_result: Optional[str] = None
    full_blood_count: Optional[str] = None
    pcv_haemoglobin: Optional[float] = Field(None, description="PCV/Haemoglobin value")
    
    # F. Treatment & Management
    ribavirin_initiated: YesNoUnknown
    date_ribavirin_initiated: Optional[datetime] = None
    ribavirin_regimen: Optional[str] = None
    supportive_care_provided: Optional[str] = None
    required_icu_admission: YesNoUnknown
    required_dialysis: YesNoUnknown
    outcome: Outcome
    date_of_discharge_or_death: Optional[datetime] = None
    
    # G. Infection Prevention & Control (IPC)
    patient_isolation_status: IsolationStatus
    healthcare_worker_infection: YesNoUnknown
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)




class LassaHealthCase(LassaFeverCase, table=True):
    __tablename__ = "lassa_fever_reports"
    id: Optional[int] = Field(default=None, primary_key=True)
    reported_at: datetime = Field(default_factory=datetime.now)
    reporter_id: Optional[str] = Field(default=None, foreign_key="health_workers.id")

class LassaFeverCaseCreate(LassaFeverCase):
    pass
