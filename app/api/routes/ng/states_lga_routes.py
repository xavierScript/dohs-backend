import logging
from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from models.nigeriaGeo import State
from core.db import engine  

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ng", tags=["STATES AND LGAS"])

@router.get("/states/")
def get_states():
    try:
        with Session(engine) as session:
            states = session.exec(select(State)).all()
            logger.info("Fetched %d states", len(states))
            return states
    except Exception as e:
        logger.error("Error fetching states: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/states/{state_alias}/lgas")
def get_lgas(state_alias: str):
    try:
        with Session(engine) as session:
            state = session.exec(select(State).where(State.alias == state_alias)).first()
            if not state:
                logger.warning("State not found: %s", state_alias)
                raise HTTPException(status_code=404, detail="State not found")
            logger.info("Fetched LGAs for state: %s", state_alias)
            return state.lgas  # Ensure relationship is defined in model
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching LGAs for state %s: %s", state_alias, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
