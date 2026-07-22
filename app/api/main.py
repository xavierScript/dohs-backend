from fastapi import APIRouter

from api.routes.authentication import health
from api.routes.authentication import non_health
from api.routes.agent import chat
from api.routes.ng import states_lga_routes as ng
from core.config import settings
from api.routes.reports import report_incident
from api.routes.zoonotics import lassa_routes
from api.routes.data_integration import integration_route
from api.routes.analysis import analysis_route
from api.routes.agent import report_agent
from api.routes.dashboard import personal_dashboard
api_router = APIRouter()
api_router.include_router(non_health.router)
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(report_incident.router)
api_router.include_router(ng.router)
api_router.include_router(lassa_routes.router)
api_router.include_router(integration_route.router)
api_router.include_router(analysis_route.router)
api_router.include_router(report_agent.router)
api_router.include_router(personal_dashboard.router)   