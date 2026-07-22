from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func
from typing import List, Dict, Any

from core.db import get_session, logger
from api.routes.authentication.health import get_current_user
from models.workers_model import HealthWorker
from models.case_model import HealthCase, AnimalCase, EnvironmentalCase

# Create a new router for dashboard
router = APIRouter(
    prefix="/mobile/dashboard",
    tags=["Mobiile Dashboard Analytics"]
)

# -------------------------
# HELPER FUNCTIONS
# -------------------------
def get_week_range(date: datetime):
    """Get start and end of week for a given date"""
    start = date - timedelta(days=date.weekday())
    end = start + timedelta(days=6)
    return start.date(), end.date()

def get_month_range(date: datetime):
    """Get start and end of month for a given date"""
    start = date.replace(day=1)
    if date.month == 12:
        end = date.replace(day=31)
    else:
        end = date.replace(month=date.month+1, day=1) - timedelta(days=1)
    return start.date(), end.date()

def calculate_percentage_change(current: int, previous: int) -> float:
    """Calculate percentage change between two numbers"""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100

def get_case_count_by_period(session: Session, model, reporter_id: str, start_date: datetime, end_date: datetime) -> int:
    """Get count of cases for a specific period"""
    query = select(func.count()).where(
        model.reporter_id == reporter_id,
        model.reported_at >= start_date,
        model.reported_at <= end_date
    )
    return session.exec(query).first() or 0

def get_recent_activities(session: Session, reporter_id: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Get recent report activities across all case types"""
    activities = []
    
    # Get recent health cases
    health_cases = session.exec(
        select(HealthCase).where(
            HealthCase.reporter_id == reporter_id
        ).order_by(HealthCase.reported_at.desc()).limit(limit)
    ).all()
    
    for case in health_cases:
        activities.append({
            "type": "health",
            "case_id": case.case_id,
            "disease": case.disease,
            "reported_at": case.reported_at,
            "status": getattr(case, 'status', 'reported')
        })
    
    # Get recent animal cases
    animal_cases = session.exec(
        select(AnimalCase).where(
            AnimalCase.reporter_id == reporter_id
        ).order_by(AnimalCase.reported_at.desc()).limit(limit)
    ).all()
    
    for case in animal_cases:
        activities.append({
            "type": "animal",
            "case_id": case.case_id,
            "disease": case.disease,
            "reported_at": case.reported_at,
            "status": getattr(case, 'status', 'reported')
        })
    
    # Get recent environmental cases
    env_cases = session.exec(
        select(EnvironmentalCase).where(
            EnvironmentalCase.reporter_id == reporter_id
        ).order_by(EnvironmentalCase.reported_at.desc()).limit(limit)
    ).all()
    
    for case in env_cases:
        activities.append({
            "type": "environmental",
            "case_id": case.case_id,
            "disease": case.disease,
            "reported_at": case.reported_at,
            "status": getattr(case, 'status', 'reported')
        })
    
    # Sort all activities by creation date and return top N
    activities.sort(key=lambda x: x['reported_at'], reverse=True)
    return activities[:limit]

# -------------------------
# DASHBOARD ROUTE
# -------------------------
@router.get("/")
async def get_dashboard(
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    """
    Get dashboard analytics for the current user including:
    - Weekly reports with percentage change vs last week
    - Monthly reports with percentage change vs last month  
    - Recent activities (last 3 reports)
    """
    try:
        today = datetime.utcnow()
        reporter_id = current_user.id
        
        # Weekly Analytics
        current_week_start, current_week_end = get_week_range(today)
        last_week_start = current_week_start - timedelta(weeks=1)
        last_week_end = current_week_start - timedelta(days=1)
        
        # Current week cases
        current_week_total = 0
        for model in [HealthCase, AnimalCase, EnvironmentalCase]:
            count = get_case_count_by_period(
                session, model, reporter_id, 
                current_week_start, current_week_end
            )
            current_week_total += count
        
        # Last week cases
        last_week_total = 0
        for model in [HealthCase, AnimalCase, EnvironmentalCase]:
            count = get_case_count_by_period(
                session, model, reporter_id,
                last_week_start, last_week_end
            )
            last_week_total += count
        
        weekly_percentage_change = calculate_percentage_change(current_week_total, last_week_total)
        
        # Monthly Analytics
        current_month_start, current_month_end = get_month_range(today)
        last_month = today.replace(day=1) - timedelta(days=1)
        last_month_start, last_month_end = get_month_range(last_month)
        
        # Current month cases
        current_month_total = 0
        for model in [HealthCase, AnimalCase, EnvironmentalCase]:
            count = get_case_count_by_period(
                session, model, reporter_id,
                current_month_start, current_month_end
            )
            current_month_total += count
        
        # Last month cases
        last_month_total = 0
        for model in [HealthCase, AnimalCase, EnvironmentalCase]:
            count = get_case_count_by_period(
                session, model, reporter_id,
                last_month_start, last_month_end
            )
            last_month_total += count
        
        monthly_percentage_change = calculate_percentage_change(current_month_total, last_month_total)
        
        # Recent Activities
        recent_activities = get_recent_activities(session, reporter_id, 3)
        
        return {
            "weekly_reports": {
                "current_week": {
                    "start_date": current_week_start,
                    "end_date": current_week_end,
                    "report_count": current_week_total
                },
                "last_week": {
                    "start_date": last_week_start,
                    "end_date": last_week_end,
                    "report_count": last_week_total
                },
                "percentage_change": round(weekly_percentage_change, 2),
                "trend": "increase" if weekly_percentage_change > 0 else "decrease"
            },
            "monthly_reports": {
                "current_month": {
                    "start_date": current_month_start,
                    "end_date": current_month_end,
                    "report_count": current_month_total
                },
                "last_month": {
                    "start_date": last_month_start,
                    "end_date": last_month_end,
                    "report_count": last_month_total
                },
                "percentage_change": round(monthly_percentage_change, 2),
                "trend": "increase" if monthly_percentage_change > 0 else "decrease"
            },
            "recent_activities": recent_activities,
            "user": {
                "id": current_user.id,
                "name": f"{current_user.first_name} {current_user.last_name}",
                "email": current_user.email
            }
        }
    
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating dashboard analytics")

# -------------------------
# INDIVIDUAL DASHBOARD ENDPOINTS (Optional)
# -------------------------
@router.get("/weekly")
async def get_weekly_analytics(
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    """Get only weekly analytics"""
    today = datetime.utcnow()
    reporter_id = current_user.id
    
    current_week_start, current_week_end = get_week_range(today)
    last_week_start = current_week_start - timedelta(weeks=1)
    last_week_end = current_week_start - timedelta(days=1)
    
    current_week_total = 0
    last_week_total = 0
    
    for model in [HealthCase, AnimalCase, EnvironmentalCase]:
        # Current week
        count = get_case_count_by_period(
            session, model, reporter_id, 
            current_week_start, current_week_end
        )
        current_week_total += count
        
        # Last week
        count = get_case_count_by_period(
            session, model, reporter_id,
            last_week_start, last_week_end
        )
        last_week_total += count
    
    percentage_change = calculate_percentage_change(current_week_total, last_week_total)
    
    return {
        "current_week": {
            "start_date": current_week_start,
            "end_date": current_week_end,
            "report_count": current_week_total
        },
        "last_week": {
            "start_date": last_week_start,
            "end_date": last_week_end,
            "report_count": last_week_total
        },
        "percentage_change": round(percentage_change, 2),
        "trend": "increase" if percentage_change > 0 else "decrease"
    }

@router.get("/monthly")
async def get_monthly_analytics(
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    """Get only monthly analytics"""
    today = datetime.utcnow()
    reporter_id = current_user.id
    
    current_month_start, current_month_end = get_month_range(today)
    last_month = today.replace(day=1) - timedelta(days=1)
    last_month_start, last_month_end = get_month_range(last_month)
    
    current_month_total = 0
    last_month_total = 0
    
    for model in [HealthCase, AnimalCase, EnvironmentalCase]:
        # Current month
        count = get_case_count_by_period(
            session, model, reporter_id,
            current_month_start, current_month_end
        )
        current_month_total += count
        
        # Last month
        count = get_case_count_by_period(
            session, model, reporter_id,
            last_month_start, last_month_end
        )
        last_month_total += count
    
    percentage_change = calculate_percentage_change(current_month_total, last_month_total)
    
    return {
        "current_month": {
            "start_date": current_month_start,
            "end_date": current_month_end,
            "report_count": current_month_total
        },
        "last_month": {
            "start_date": last_month_start,
            "end_date": last_month_end,
            "report_count": last_month_total
        },
        "percentage_change": round(percentage_change, 2),
        "trend": "increase" if percentage_change > 0 else "decrease"
    }

@router.get("/recent-activities")
async def get_recent_activities_endpoint(
    limit: int = Query(3, ge=1, le=10),
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
):
    """Get recent report activities"""
    activities = get_recent_activities(session, current_user.id, limit)
    return {"recent_activities": activities}