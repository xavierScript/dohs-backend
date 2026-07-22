from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.params import Query
from sqlmodel import Session, select
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
from api.routes.reports.report_incident import get_filtered_cases
from core.db import get_session, logger
from api.routes.authentication.health import get_current_user



from models.priority_zoonotics.lassa_fever_model import LassaHealthCase, LassaFeverCaseCreate

router = APIRouter(
    prefix="/zoonotics/lassa",
    tags=["SUSPECTED LASSA ONLY"],
    
    dependencies=[Depends(get_current_user)]
)



@router.post("/")
async def create_health_case(
    data: LassaFeverCaseCreate,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user)
):
    try:
        case = LassaHealthCase(**data.dict(), reporter_id=current_user.id)
        session.add(case)
        session.commit()
        session.refresh(case)
        return {"message": "Case created successful", "Case ID": case.patient_id}
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error creating health case: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database error creating health case")
    except Exception as e:
        session.rollback()
        logger.error(f"Unexpected error creating health case: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected error creating health case")
    

@router.get("/")
async def list_all_lassa_cases(
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
        session, LassaHealthCase, search, reporter_id, start_date, end_date,
        sort_by, sort_order, page, page_size
    )

    


# -------------------------
# UPDATE HEALTH REPORT (Only Reporter Can Update)
# -------------------------
@router.put("/health/{patient_id}")
async def update_health_case(
    patient_id: str,
    data: LassaFeverCaseCreate,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user)
):
    case = session.exec(select(LassaHealthCase).where(LassaHealthCase.patient_id == patient_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case.reporter_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this case")

    for key, value in data.dict().items():
        setattr(case, key, value)

    session.add(case)
    session.commit()
    session.refresh(case)
    return case

