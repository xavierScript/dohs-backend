from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.params import Query
from sqlmodel import Session, select
from sqlalchemy.exc import SQLAlchemyError
from typing import Any, Dict, List, Optional
from api.routes.reports.report_incident import get_filtered_cases
from core.db import get_session, logger
from api.routes.authentication.health import get_current_user
from models.case_model import (
    HealthCase,
    AnimalCase,
    EnvironmentalCase
)
router = APIRouter(prefix="/integrated", tags=["Integration"])

@router.get("/cases")
def get_unified_cases(session: Session = Depends(get_session)) -> List[Dict[str, Any]]:
    health_cases = session.exec(select(HealthCase)).all()
    animal_cases = session.exec(select(AnimalCase)).all()
    env_cases = session.exec(select(EnvironmentalCase)).all()

    def normalize_case(c):
        return {
            "case_id": c.case_id,
            "personID": getattr(c, "personID", None),
            "disease": c.disease,
            "classification": c.classification,
            "outcome": c.outcome,
            "longitude": c.longitude,
            "latitude": c.latitude,
            "state": c.state,
            "lga": c.lga,
            "health_facility": c.health_facility,
            "region": c.region,
            "reporting_source": c.reporting_source,
            "date_of_onset": c.date_of_onset,
            "date_of_confirmation": c.date_of_confirmation,
            "category": getattr(c, "category", "Unknown"),
            "additional_data": {
                "symptoms": getattr(c, "symptoms", None),
                "risk_factors": getattr(c, "risk_factors", None),
                "animal_species": getattr(c, "animal_species", None),
                "environmental_factors": getattr(c, "environmental_factors", None),
                "lab_results": getattr(c, "lab_results", None),
            },
            "reported_at": getattr(c, "reported_at", None),
        }

    unified = [normalize_case(c) for c in (health_cases + animal_cases + env_cases)]
    unified.sort(key=lambda x: x["reported_at"], reverse=True)

    return unified
