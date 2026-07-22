from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import numpy as np
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
from models import HealthCase, AnimalCase, EnvironmentalCase
from core.db import get_session, logger
from core.clustering import haversine_distance, region_query, dbscan

router = APIRouter(prefix="/analysis", tags=["Analysis"])

# -------------------------------------------------------------------
# 📦 Pydantic models for request/response
# -------------------------------------------------------------------

class ClusterCase(BaseModel):
    case_id: str
    disease: str
    category: str
    latitude: float
    longitude: float
    reported_at: str


class ClusterCenter(BaseModel):
    lat: float
    lng: float


class TimeWindow(BaseModel):
    start: str
    end: str


class ClusterResponse(BaseModel):
    cluster_id: int
    cases: List[ClusterCase]
    disease_types: List[str]
    time_window: TimeWindow
    center: ClusterCenter
    case_count: int


class ClustersSummary(BaseModel):
    total_clusters: int
    total_cases_in_clusters: int
    total_cases_analyzed: int
    noise_cases: int
    clusters: List[ClusterResponse]


class AnalysisParameters(BaseModel):
    radius_km: float = 10.0
    min_samples: int = 3
    days_back: Optional[int] = None
    categories: Optional[List[str]] = None


# -------------------------------------------------------------------
# ⚙️ Custom DBSCAN implementation (imported from core/clustering.py)
# haversine_distance, region_query, and dbscan are defined in
# core/clustering.py so they can be imported by evaluation scripts
# without triggering the database engine.
# -------------------------------------------------------------------


# -------------------------------------------------------------------
# 🧩 Helper functions for database and validation
# -------------------------------------------------------------------

def get_valid_cases(session: Session, days_back: Optional[int] = None, categories: Optional[List[str]] = None) -> List:
    """Fetch valid cases with coordinates and optional filters."""
    health_query = select(HealthCase).where(HealthCase.latitude.isnot(None), HealthCase.longitude.isnot(None))
    animal_query = select(AnimalCase).where(AnimalCase.latitude.isnot(None), AnimalCase.longitude.isnot(None))
    env_query = select(EnvironmentalCase).where(EnvironmentalCase.latitude.isnot(None), EnvironmentalCase.longitude.isnot(None))

    if days_back:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        health_query = health_query.where(HealthCase.reported_at >= cutoff_date)
        animal_query = animal_query.where(AnimalCase.reported_at >= cutoff_date)
        env_query = env_query.where(EnvironmentalCase.reported_at >= cutoff_date)

    health_cases = session.exec(health_query).all()
    animal_cases = session.exec(animal_query).all()
    env_cases = session.exec(env_query).all()

    all_cases = [*health_cases, *animal_cases, *env_cases]

    if categories:
        all_cases = [case for case in all_cases if getattr(case, "category", "Unknown") in categories]

    return all_cases


def validate_coordinates(lat: float, lng: float) -> bool:
    """Check if coordinates are within valid range."""
    return -90 <= lat <= 90 and -180 <= lng <= 180


# -------------------------------------------------------------------
# 🚀 API Endpoints
# -------------------------------------------------------------------

@router.get("/clusters", response_model=ClustersSummary)
def detect_clusters(
    radius_km: float = 10.0,
    min_samples: int = 3,
    days_back: Optional[int] = None,
    categories: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """
    Detect spatial clusters of health, animal, and environmental cases.
    """

    try:
        # Parse and validate inputs
        category_list = [c.strip() for c in categories.split(",")] if categories else None

        if radius_km <= 0:
            raise HTTPException(status_code=400, detail="Radius must be positive")
        if min_samples < 2:
            raise HTTPException(status_code=400, detail="Minimum samples must be at least 2")
        if days_back and days_back <= 0:
            raise HTTPException(status_code=400, detail="Days back must be positive")

        # Fetch all cases
        all_cases = get_valid_cases(session, days_back, category_list)

        if not all_cases:
            return ClustersSummary(
                total_clusters=0,
                total_cases_in_clusters=0,
                total_cases_analyzed=0,
                noise_cases=0,
                clusters=[],
            )

        points = []
        valid_cases = []

        for case in all_cases:
            if case.latitude is not None and case.longitude is not None and validate_coordinates(case.latitude, case.longitude):
                points.append([case.latitude, case.longitude])
                valid_cases.append(case)

        if len(points) < min_samples:
            logger.info(f"Not enough valid data for clustering. Found {len(points)} points.")
            return ClustersSummary(
                total_clusters=0,
                total_cases_in_clusters=0,
                total_cases_analyzed=len(valid_cases),
                noise_cases=len(valid_cases),
                clusters=[],
            )

        points_array = np.array(points)

        # Run custom DBSCAN
        labels = dbscan(points_array, eps_km=radius_km, min_samples=min_samples)

        # Build clusters
        clusters = {}
        noise_cases = 0

        for label, case in zip(labels, valid_cases):
            if label == -1:
                noise_cases += 1
                continue
            clusters.setdefault(label, []).append({
                "case_id": str(getattr(case, "case_id", f"unknown_{id(case)}")),
                "disease": getattr(case, "disease", "Unknown"),
                "category": getattr(case, "category", "Unknown"),
                "latitude": float(case.latitude),
                "longitude": float(case.longitude),
                "reported_at": case.reported_at.isoformat() if hasattr(case.reported_at, "isoformat") else str(case.reported_at),
            })

        cluster_responses = []
        for cluster_id, cases in clusters.items():
            if len(cases) >= min_samples:
                latitudes = [c["latitude"] for c in cases]
                longitudes = [c["longitude"] for c in cases]
                reported_dates = [c["reported_at"] for c in cases]
                cluster_responses.append(
                    ClusterResponse(
                        cluster_id=cluster_id,
                        cases=[ClusterCase(**c) for c in cases],
                        disease_types=sorted(list({c["disease"] for c in cases})),
                        time_window=TimeWindow(
                            start=min(reported_dates),
                            end=max(reported_dates),
                        ),
                        center=ClusterCenter(
                            lat=float(np.mean(latitudes)),
                            lng=float(np.mean(longitudes)),
                        ),
                        case_count=len(cases),
                    )
                )

        total_clustered_cases = sum(len(c.cases) for c in cluster_responses)

        return ClustersSummary(
            total_clusters=len(cluster_responses),
            total_cases_in_clusters=total_clustered_cases,
            total_cases_analyzed=len(valid_cases),
            noise_cases=noise_cases,
            clusters=cluster_responses,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in cluster detection: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during cluster analysis")


@router.post("/clusters/advanced", response_model=ClustersSummary)
def detect_clusters_advanced(params: AnalysisParameters, session: Session = Depends(get_session)):
    """Advanced clustering endpoint (POST body input)."""
    return detect_clusters(
        radius_km=params.radius_km,
        min_samples=params.min_samples,
        days_back=params.days_back,
        categories=",".join(params.categories) if params.categories else None,
        session=session,
    )
