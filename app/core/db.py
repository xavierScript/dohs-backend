import logging
from sqlmodel import Session, create_engine, select
import json
import os
from models.nigeriaGeo import LGA, State
from core.config import settings
from models.workers_model import HealthWorker, HealthWorkerCreate, NonHealthWorkerRead
from models.workers_model import SQLModel
from pathlib import Path



# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLOUD_DB_URI = os.getenv("CLOUD_DB_URI")

try:
    engine = create_engine(str(CLOUD_DB_URI))
    logger.info("Database engine created successfully.")
except Exception as e:
    logger.error("Error creating database engine: %s", e)
    raise


def init_db() -> None:
    try:
        SQLModel.metadata.create_all(engine)
        logger.info("Database initialized successfully.")
        with Session(engine) as session:
            existing_states = session.exec(select(State)).first()
            logger.info("Existing states in DB: %s", existing_states)
            if not existing_states:
                logger.info("Seeding Nigeria states/LGAs data...")
                seed_nigeria_data(session)
            else:
                logger.info("States already exist. Skipping seeding.")
    except Exception as e:
        logger.exception("Error initializing the database")
        raise

def seed_nigeria_data(session: Session):
    json_path = Path("data/nigeria_states.json")
    logger.info("Looking for Nigeria states JSON at: %s", json_path.resolve())
    if not json_path.exists():
        logger.error("Nigeria states JSON file not found at %s", json_path)
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            states_data = json.load(f)
        logger.info("Loaded %d states from JSON.", len(states_data))
    except json.JSONDecodeError as e:
        logger.error("Error decoding JSON from %s: %s", json_path, e)
        return
    except Exception as e:
        logger.exception("Unexpected error reading Nigeria states JSON")
        return

    for state_data in states_data:
        try:
            state = State(
                name=state_data["state"],
                alias=state_data.get("alias", state_data["state"])
            )
            session.add(state)
            session.commit()
            session.refresh(state)
            logger.info("Added state: %s (ID: %s)", state.name, state.id)

            # Now add LGAs
            for lga_name in state_data.get("lgas", []):
                lga = LGA(name=lga_name, state_id=state.id)
                session.add(lga)
            
            session.commit()
            logger.info("Added %d LGAs for state: %s", len(state_data.get("lgas", [])), state.name)

        except Exception as e:
            logger.error("Error adding state or LGAs for %s: %s", state_data.get("state"), e)
            session.rollback()

    logger.info("Nigeria states and LGAs seeded successfully.")


def get_session():
    try:
        with Session(engine) as session:
            logger.info("Database session created successfully.")
            yield session
    except Exception as e:
        logger.exception("Error creating database session")
        raise


init_db()