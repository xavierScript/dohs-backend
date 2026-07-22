from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
import httpx
import asyncio
import json

from models.workers_model import HealthWorker
from core.db import get_session, logger
from api.routes.authentication.health import get_current_user
from models.case_model import (
    HealthCase, HealthCaseCreate, HealthCaseRead,
    AnimalCase, AnimalCaseCreate, AnimalCaseRead,
    EnvironmentalCase, EnvironmentalCaseCreate, EnvironmentalCaseRead
)

router = APIRouter(
    prefix="/reports",
    tags=["GENERAL Reports FOR UNCLASSIFIED DISEASE ONLY"],
)

# -------------------------
# CONFIGURATION
# -------------------------
N8N_WEBHOOK_URL = "https://dohs-n8n.fllxmx.easypanel.host/webhook-test/11b017e3-34a3-4017-8e1d-127f95742207"
N8N_WEBHOOK_TIMEOUT = 30

# -------------------------
# HELPER: Send to n8n Webhook
# -------------------------
async def send_to_n8n_webhook(case_data: dict):
    """Send case data to n8n webhook asynchronously"""
    try:
        async with httpx.AsyncClient(timeout=N8N_WEBHOOK_TIMEOUT) as client:
            response = await client.post(
                N8N_WEBHOOK_URL,
                json=case_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully sent case {case_data['case_id']} to n8n webhook")
            else:
                logger.warning(f"n8n webhook returned status {response.status_code}: {response.text}")
                
    except Exception as e:
        logger.error(f"Error sending to n8n webhook: {str(e)}")




# -------------------------
# HELPER: Generic filtering, searching, sorting, and pagination
# -------------------------
def get_filtered_cases(
    session: Session,
    model,
    search: Optional[str] = None,
    reporter_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 10
):
    query = select(model)

    if reporter_id:
        query = query.where(model.reporter_id == reporter_id)
    if start_date:
        query = query.where(model.created_at >= start_date)
    if end_date:
        query = query.where(model.created_at <= end_date)
    if search and hasattr(model, "disease"):
        query = query.where(model.disease.ilike(f"%{search}%"))

    if hasattr(model, sort_by):
        sort_column = getattr(model, sort_by)
        if sort_order.lower() == "desc":
            sort_column = sort_column.desc()
        query = query.order_by(sort_column)

    results = session.exec(query.offset((page - 1) * page_size).limit(page_size)).all()
    total = len(results)

    return {"total": total, "page": page, "page_size": page_size, "items": results}





# -------------------------
# HELPER: Check for Severe Lassa Fever Criteria
# -------------------------
def is_severe_lassa_fever_case(symptoms: Optional[str], classification: str, outcome: str) -> bool:
    """
    Check if case meets severe Lassa fever criteria based on national guidelines
    """
    if not symptoms:
        return False
    
    # Convert symptoms string to list and lowercase for matching
    symptom_list = [s.strip().lower() for s in symptoms.split(',')]
    
    # Severe symptoms indicating critical Lassa fever
    severe_symptoms = {
        'bleeding', 'hemorrhage', 'bleeding from gums', 'blood in stool', 'blood in urine',
        'neurological', 'seizure', 'confusion', 'disorientation', 'coma', 'unconsciousness',
        'respiratory distress', 'difficulty breathing', 'shortness of breath', 
        'hypotension', 'low blood pressure', 'shock',
        'organ failure', 'kidney failure', 'liver failure',
        'facial swelling', 'chest pain', 'abdominal pain'
    }
    
    # Check for severe symptoms
    has_severe_symptoms = any(symptom in severe_symptoms for symptom in symptom_list)
    
    # Check classification and outcome
    is_confirmed = classification.lower() == 'confirmed'
    is_fatal = outcome.lower() == 'dead'
    
    return has_severe_symptoms or is_fatal or is_confirmed

# -------------------------
# HELPER: Prepare n8n Payload
# -------------------------
def prepare_n8n_payload(case, case_type: str) -> dict:
    """Prepare standardized payload for n8n webhook"""
    
    base_payload = {
        "case_id": case.case_id,
        "person_id": case.personID,
        "disease": case.disease,
        "classification": case.classification,
        "outcome": case.outcome,
        "state": case.state,
        "lga": case.lga,
        "health_facility": case.health_facility,
        "region": case.region,
        "longitude": case.longitude,
        "latitude": case.latitude,
        "date_of_onset": case.date_of_onset.isoformat() if case.date_of_onset else None,
        "date_of_confirmation": case.date_of_confirmation.isoformat() if case.date_of_confirmation else None,
        "reported_at": case.reported_at.isoformat(),
        "case_type": case_type,
        "category": case.category
    }
    
    # Add type-specific fields
    if case_type == "health":
        base_payload.update({
            "age": case.age,
            "sex": case.sex,
            "occupation": case.occupation,
            "symptoms": case.symptoms,
            "risk_factors": case.risk_factors,
            "is_severe_lassa": (
                case.disease.lower() == "lassa fever" and 
                is_severe_lassa_fever_case(case.symptoms, case.classification, case.outcome)
            )
        })
    elif case_type == "animal":
        base_payload.update({
            "animal_species": case.animal_species,
            "number_affected": case.number_affected,
            "symptoms": case.symptoms,
            "lab_results": case.lab_results
        })
    elif case_type == "environmental":
        base_payload.update({
            "environmental_factors": case.environmental_factors,
            "sample_collected": case.sample_collected,
            "lab_results": case.lab_results
        })
    
    return base_payload

# -------------------------
# CREATE HEALTH CASE (With n8n Webhook)
# -------------------------
@router.post("/health", response_model=dict, name="create_health_case")
async def create_health_case(
    data: HealthCaseCreate,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    try:
        # Create the health case
        _request_received_at = datetime.utcnow()
        case_data = data.dict()
        case = HealthCase(**case_data, reporter_id=current_user.id, reported_at=datetime.utcnow())
        session.add(case)
        session.commit()
        session.refresh(case)
        _db_commit_ms = (datetime.utcnow() - _request_received_at).total_seconds() * 1000
        logger.info(f"LATENCY_METRIC case_id={case.case_id} db_commit_ms={_db_commit_ms:.2f}")
        
        # Prepare and send data to n8n webhook (in background)
        n8n_payload = prepare_n8n_payload(case, "health")
        asyncio.create_task(send_to_n8n_webhook(n8n_payload))
        
        return {
            "message": "Health case created successfully", 
            "case_id": case.case_id,
            "person_id": case.personID,
            "sent_to_monitoring": True,
            "is_severe_lassa": n8n_payload.get("is_severe_lassa", False)
        }
        
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error creating health case: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database error creating health case")

# # -------------------------
# # CREATE ANIMAL CASE (With n8n Webhook)
# # -------------------------
# @router.post("/animal", response_model=dict, name="create_animal_case")
# async def create_animal_case(
#     data: AnimalCaseCreate,
#     session: Session = Depends(get_session),
#     current_user: HealthWorker = Depends(get_current_user)
# ):
#     try:
#         # Create the animal case
#         case_data = data.dict()
#         case = AnimalCase(**case_data, reporter_id=current_user.id, reported_at=datetime.utcnow())
#         session.add(case)
#         session.commit()
#         session.refresh(case)
        
#         # Prepare and send data to n8n webhook
#         n8n_payload = prepare_n8n_payload(case, "animal", current_user)
#         asyncio.create_task(send_to_n8n_webhook(n8n_payload))
        
#         return {
#             "message": "Animal case created successfully", 
#             "case_id": case.case_id,
#             "sent_to_monitoring": True
#         }
        
#     except SQLAlchemyError as e:
#         session.rollback()
#         logger.error(f"Database error creating animal case: {str(e)}", exc_info=True)
#         raise HTTPException(status_code=500, detail="Database error creating animal case")

# # -------------------------
# # CREATE ENVIRONMENTAL CASE (With n8n Webhook)
# # -------------------------
# @router.post("/environmental", response_model=dict, name="create_environmental_case")
# async def create_environmental_case(
#     data: EnvironmentalCaseCreate,
#     session: Session = Depends(get_session),
#     current_user: HealthWorker = Depends(get_current_user)
# ):
#     try:
#         # Create the environmental case
#         case_data = data.dict()
#         case = EnvironmentalCase(**case_data, reporter_id=current_user.id, reported_at=datetime.utcnow())
#         session.add(case)
#         session.commit()
#         session.refresh(case)
        
#         # Prepare and send data to n8n webhook
#         n8n_payload = prepare_n8n_payload(case, "environmental", current_user)
#         asyncio.create_task(send_to_n8n_webhook(n8n_payload))
        
#         return {
#             "message": "Environmental case created successfully", 
#             "case_id": case.case_id,
#             "sent_to_monitoring": True
#         }
        
#     except SQLAlchemyError as e:
#         session.rollback()
#         logger.error(f"Database error creating environmental case: {str(e)}", exc_info=True)
#         raise HTTPException(status_code=500, detail="Database error creating environmental case")

# -------------------------
# BULK NOTIFICATION ENDPOINT
# -------------------------
@router.post("/notify-n8n/{case_id}", response_model=dict, name="trigger_n8n_notification")
async def trigger_n8n_notification(
    case_id: str,
    case_type: str = Query(..., description="Type of case: health, animal, or environmental"),
    session: Session = Depends(get_session),

):
    """Manually trigger n8n notification for an existing case"""
    try:
        case = None
        if case_type == "health":
            case = session.exec(select(HealthCase).where(HealthCase.case_id == case_id)).first()
        elif case_type == "animal":
            case = session.exec(select(AnimalCase).where(AnimalCase.case_id == case_id)).first()
        elif case_type == "environmental":
            case = session.exec(select(EnvironmentalCase).where(EnvironmentalCase.case_id == case_id)).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Prepare and send data to n8n webhook
        n8n_payload = prepare_n8n_payload(case, case_type)
        await send_to_n8n_webhook(n8n_payload)
        
        return {
            "message": "Notification sent to n8n successfully",
            "case_id": case.case_id,
            "case_type": case_type,
            "is_severe_lassa": n8n_payload.get("is_severe_lassa", False)
        }
        
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching case: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database error")
        
# -------------------------
# LIST HEALTH REPORTS (Public)
# -------------------------
@router.get("/health")
async def list_health_cases(
    search: Optional[str] = Query(None),
    reporter_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session)
):
    return get_filtered_cases(
        session, HealthCase, search, reporter_id, start_date, end_date,
        sort_by, sort_order, page, page_size
    )


# -------------------------
# UPDATE HEALTH REPORT (Requires Auth)
# -------------------------
@router.put("/health/{case_id}")
async def update_health_case(
    case_id: str,
    data: HealthCaseCreate,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    case = session.exec(select(HealthCase).where(HealthCase.case_id == case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    for key, value in data.dict().items():
        setattr(case, key, value)

    session.add(case)
    session.commit()
    session.refresh(case)
    return {"message": "Case updated successfully", "Case ID": case.case_id}

# -------------------------
# DELETE HEALTH REPORT (Requires Auth)
# -------------------------
@router.delete("/health/{case_id}")
async def delete_health_case(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    case = session.exec(select(HealthCase).where(HealthCase.case_id == case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    session.delete(case)
    session.commit()
    return {"message": "Case deleted successfully", "case_id": case_id}


# -------------------------
# CREATE ANIMAL REPORT (Requires Auth)
# -------------------------
@router.post("/animal")
async def create_animal_case(
    data: AnimalCaseCreate,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    try:
        case = AnimalCase(**data.dict(), reporter_id=current_user.id, reported_at=datetime.utcnow())
        session.add(case)
        session.commit()
        session.refresh(case)
        return {"message": "Case created successfully", "Case ID": case.case_id}
    except SQLAlchemyError:
        session.rollback()
        logger.error("Error creating animal case", exc_info=True)
        raise HTTPException(status_code=500, detail="Error creating animal case")


# -------------------------
# LIST ANIMAL REPORTS (Public)
# -------------------------
@router.get("/animal")
async def list_animal_cases(
    search: Optional[str] = Query(None),
    reporter_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session)
):
    return get_filtered_cases(
        session, AnimalCase, search, reporter_id, start_date, end_date,
        sort_by, sort_order, page, page_size
    )


# -------------------------
# UPDATE ANIMAL REPORT (Requires Auth)
# -------------------------
@router.put("/animal/{case_id}")
async def update_animal_case(
    case_id: str,
    data: AnimalCaseCreate,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    case = session.exec(select(AnimalCase).where(AnimalCase.case_id == case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    for key, value in data.dict().items():
        setattr(case, key, value)

    session.add(case)
    session.commit()
    session.refresh(case)
    return {"message": "Case updated successfully", "Case ID": case.case_id}


# -------------------------
# DELETE ANIMAL REPORT (Requires Auth)
# -------------------------
@router.delete("/animal/{case_id}")
async def delete_animal_case(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    case = session.exec(select(AnimalCase).where(AnimalCase.case_id == case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    session.delete(case)
    session.commit()
    return {"message": "Case deleted successfully", "Case ID": case.case_id}





# -------------------------
# CREATE ENVIRONMENTAL REPORT (Requires Auth)
# -------------------------
@router.post("/env")
async def create_env_case(
    data: EnvironmentalCaseCreate,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user),
):
    try:
        case = EnvironmentalCase(**data.dict(), reporter_id=current_user.id, reported_at=datetime.utcnow())
        session.add(case)
        session.commit()
        session.refresh(case)
        return {"message": "Case created successfully", "Case ID": case.case_id}
    except SQLAlchemyError:
        session.rollback()
        logger.error("Error creating environmental case", exc_info=True)
        raise HTTPException(status_code=500, detail="Error creating environmental case")


# -------------------------
# LIST ENVIRONMENTAL REPORTS (Public)
# -------------------------
@router.get("/env")
async def list_env_cases(
    search: Optional[str] = Query(None),
    reporter_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_session)
):
    return get_filtered_cases(
        session, EnvironmentalCase, search, reporter_id, start_date, end_date,
        sort_by, sort_order, page, page_size
    )


# -------------------------
# UPDATE & DELETE ENVIRONMENTAL REPORT (Requires Auth)
# -------------------------
@router.put("/env/{case_id}")
async def update_env_case(
    case_id: str,
    data: EnvironmentalCaseCreate,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    case = session.exec(select(EnvironmentalCase).where(EnvironmentalCase.case_id == case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    for key, value in data.dict().items():
        setattr(case, key, value)

    session.add(case)
    session.commit()
    session.refresh(case)
    return {"message": "Case updated successfully", "Case ID": case.case_id}


@router.delete("/env/{case_id}")
async def delete_env_case(
    case_id: str,
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    case = session.exec(select(EnvironmentalCase).where(EnvironmentalCase.case_id == case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    session.delete(case)
    session.commit()
    return {"message": "Case deleted successfully", "Case ID": case.case_id}
