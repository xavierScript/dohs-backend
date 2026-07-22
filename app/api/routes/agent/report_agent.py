# routes/report_agent.py
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import httpx
import json
from datetime import datetime, timedelta

from sqlmodel import Session

from api.routes.authentication.health import get_current_user, read_profile
from core.db import get_session
from models.workers_model import HealthWorker
auth_scheme = HTTPBearer()
router = APIRouter(prefix="/agent", tags=["WITH AUTH"], dependencies=[Depends(get_current_user)])

# In-memory session storage (use Redis in production)
user_sessions = {}

# Essential fields only
ESSENTIAL_FIELDS = [
    "disease", "classification", "outcome", "date_of_onset", 
    "date_of_confirmation", "age", "sex", "symptoms", "risk_factors"
]

# Group fields for more natural conversation flow
FIELD_GROUPS = {
    "case_identification": ["disease", "classification"],
    "timeline": ["date_of_onset", "date_of_confirmation"],
    "patient_details": ["age", "sex"],
    "clinical_info": ["symptoms", "risk_factors", "outcome"]
}

class ReportAgentRequest(BaseModel):
    prompt: str = Field( min_length=1, default='Reporting a suspected Lassa fever case in a 25-year-old female healthcare worker. Symptoms started 3 days ago with fever and sore throat, we classified it as suspected on Today. Patient has recovered fully. Had possible exposure while treating febrile patients. Presented with mild symptoms: fatigue and muscle pain.', description="The prompt for the AI model")
    session_id: Optional[str] = Field(None, description="Session ID for continuous conversation")
    health_worker_id: Optional[str] = Field(None, description="Health worker ID for auto-population")

class UserSession:
    def __init__(self, health_worker_data: Dict[str, Any] = None):
        self.extracted_data = {}
        self.missing_fields = ESSENTIAL_FIELDS.copy()
        self.conversation_history = []
        self.health_worker_data = health_worker_data or {}
        self.attempted_multi_extraction = False
        
        # Auto-populate from health worker data
        if health_worker_data:
            self._populate_from_health_worker()
    
    def _populate_from_health_worker(self):
        """Auto-populate fields from health worker information"""
        auto_fields = {
            "state": self.health_worker_data.get("state"),
            "lga": self.health_worker_data.get("lga"), 
            "health_facility": self.health_worker_data.get("facility"),
            "region": self.health_worker_data.get("state"),
            "longitude": self.health_worker_data.get("longitude"),
            "latitude": self.health_worker_data.get("latitude"),
            "reporting_source": f"Health Worker: {self.health_worker_data.get('first_name', '')} {self.health_worker_data.get('last_name', '')}"
        }
        
        for field, value in auto_fields.items():
            if value and value != "Unknown":
                self.extracted_data[field] = value
    
    def update_field(self, field: str, value: Any):
        """Update a field and remove from missing fields"""
        if value is not None and value != "":
            self.extracted_data[field] = value
            if field in self.missing_fields:
                self.missing_fields.remove(field)
    
    def get_next_questions(self, count: int = 3) -> List[str]:
        """Get the next set of questions for the user (2-4 fields at once)"""
        if not self.missing_fields:
            return None
        
        # Group related fields together for more natural conversation
        questions = []
        remaining_fields = self.missing_fields.copy()
        
        # Try to ask about related fields together
        for group_name, group_fields in FIELD_GROUPS.items():
            group_missing = [f for f in group_fields if f in remaining_fields]
            if group_missing:
                if len(group_missing) == 1:
                    questions.append(self._get_single_question(group_missing[0]))
                    remaining_fields.remove(group_missing[0])
                else:
                    questions.append(self._get_group_question(group_missing))
                    for field in group_missing:
                        if field in remaining_fields:
                            remaining_fields.remove(field)
                
                if len(questions) >= count or len(remaining_fields) == 0:
                    break
        
        # If we still have room, add individual questions
        while len(questions) < count and remaining_fields:
            field = remaining_fields[0]
            questions.append(self._get_single_question(field))
            remaining_fields.remove(field)
        
        return questions
    
    def _get_single_question(self, field: str) -> str:
        """Get question for a single field"""
        field_questions = {
            "disease": "What disease are you reporting?",
            "classification": "What is the classification? (suspected, probable, confirmed)",
            "outcome": "What is the patient outcome? (recovered, died, undergoing treatment)",
            "date_of_onset": "When did symptoms start? (e.g., 2024-01-15 or 'yesterday')",
            "date_of_confirmation": "When was this confirmed? (e.g., 2024-01-16 or 'today')",
            "age": "What is the patient's age?",
            "sex": "What is the patient's gender? (male/female)",
            "symptoms": "What symptoms were observed?",
            "risk_factors": "Any known risk factors?"
        }
        return field_questions.get(field, f"What is the {field}?")
    
    def _get_group_question(self, fields: List[str]) -> str:
        """Get a combined question for related fields"""
        field_groups = {
            ("disease", "classification"): "What disease are you reporting and what is its classification? (suspected, probable, confirmed)",
            ("date_of_onset", "date_of_confirmation"): "When did symptoms start and when was the case confirmed?",
            ("age", "sex"): "What is the patient's age and gender?",
            ("symptoms", "risk_factors"): "What symptoms were observed and any known risk factors?",
            ("symptoms", "outcome"): "What symptoms were observed and what's the current outcome?",
        }
        
        # Try to find exact match
        field_tuple = tuple(sorted(fields))
        if field_tuple in field_groups:
            return field_groups[field_tuple]
        
        # Fallback to generic combined question
        return f"Can you provide information about: {', '.join(fields)}?"

async def get_health_worker_data(worker_id: str) -> Dict[str, Any]:
    """Fetch health worker data from your database"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://backend.onehealth-wwrg.com/api/v1/health-workers/{worker_id}",
                timeout=10.0
            )
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    
    return {
        "first_name": "John",
        "last_name": "Doe", 
        "facility": "Central Hospital",
        "state": "Lagos",
        "lga": "Ikeja",
        "latitude": 6.5244,
        "longitude": 3.3792
    }

async def extract_essential_fields(prompt: str, health_worker_data: Dict[str, Any], missing_fields: List[str] = None) -> Dict[str, Any]:
    """Extract essential fields using LLM, focusing on missing fields"""
    if missing_fields is None:
        missing_fields = ESSENTIAL_FIELDS
    
    system_prompt = f"""You are a medical report assistant. Extract ONLY these essential fields from the user's message:

Fields to extract: {', '.join(missing_fields)}

Field definitions:
- disease: The disease name (e.g., cholera, malaria, covid)
- classification: suspected, probable, or confirmed
- outcome: recovered, died, or undergoing treatment  
- date_of_onset: When symptoms started (convert to YYYY-MM-DD format)
- date_of_confirmation: When case was confirmed (convert to YYYY-MM-DD format)
- age: Patient age (number)
- sex: male or female
- symptoms: Description of symptoms
- risk_factors: Any risk factors mentioned

Health Worker Context:
- Facility: {health_worker_data.get('facility', 'Unknown')}
- Location: {health_worker_data.get('state', 'Unknown')}, {health_worker_data.get('lga', 'Unknown')}

Return ONLY a JSON object with the extracted fields. Use null for missing fields.
If user provides relative dates like "today" or "yesterday", convert to YYYY-MM-DD format.
Current date: {datetime.now().strftime('%Y-%m-%d')}
"""

    payload = {
        "model": "llama3.2:latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_predict": 100
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://dohs-ollama.fllxmx.easypanel.host/api/chat",
                json=payload,
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            extracted = data["message"]["content"].strip()
            
            # Clean JSON response
            if "```json" in extracted:
                extracted = extracted.split("```json")[1].split("```")[0].strip()
            elif "```" in extracted:
                extracted = extracted.split("```")[1].split("```")[0].strip()
                
            return json.loads(extracted)
            
    except Exception as e:
        print(f"LLM extraction error: {e}")
        return {}

@router.post("/report")
async def collect_report(
    request: ReportAgentRequest, 
    credentials: HTTPAuthorizationCredentials = Depends(auth_scheme),
    session: Session = Depends(get_session),
    current_user: HealthWorker = Depends(get_current_user)
    ):
 


    user_input = request.prompt.strip()
    session_id = request.session_id or "default"
    health_worker_id = request.health_worker_id
    
    # Get health worker data if provided
    health_worker_data = current_user.dict()
    if health_worker_id:
        health_worker_data =  read_profile(current_user=current_user)
    
    
    # Get or create session
    if session_id not in user_sessions:
        user_sessions[session_id] = UserSession(health_worker_data)
    
    session_obj = user_sessions[session_id]
    session_obj.conversation_history.append(f"User: {user_input}")
    
    # Always try to extract multiple fields from the input
    missing_fields = session_obj.missing_fields.copy()
    if missing_fields:
        extracted_data = await extract_essential_fields(user_input, health_worker_data, missing_fields)
        
        # Update session with extracted fields
        extracted_count = 0
        for field in missing_fields:
            if field in extracted_data and extracted_data[field] is not None:
                session_obj.update_field(field, extracted_data[field])
                extracted_count += 1
        
        if extracted_count > 0:
            session_obj.conversation_history.append(f"System: Extracted {extracted_count} fields from input")
    
    # Check if we have all essential fields
    if not session_obj.missing_fields:
        # Prepare final payload
        payload = session_obj.extracted_data.copy()
        payload["category"] = "Human"
        if health_worker_data:
            payload.update({
                "state": health_worker_data.get("state"),
                "lga": health_worker_data.get("lga"),
                "health_facility": health_worker_data.get("facility"),
                "reporting_source": f"Health Worker: {health_worker_data.get('first_name', '')} {health_worker_data.get('last_name', '')}"
            })
    
        
        # Add auto-generated fields
        payload["case_id"] = f"CASE-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        payload["personID"] = f"PERSON-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


        print("Final payload to submit:", payload)
        
        # Submit to backend
        try:
            async with httpx.AsyncClient() as client:
                headers = {}
                token = credentials.credentials 
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                res = await client.post(
                    "http://localhost:8000/api/v1/reports/health",
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                
                if res.status_code == 200:
                    # Clear session after successful submission
                    del user_sessions[session_id]
                    return {
                        "reply": "✅ Report submitted successfully!",
                        "session_id": session_id,
                        "completed": True,
                        "submitted_data": payload
                    }
                else:
                    return {
                        "reply": f"❌ Submission failed: {res.text}",
                        "session_id": session_id,
                        "completed": False,
                        'token': headers
                    }
                    
        except Exception as e:
            return {
                "reply": f"❌ Submission error: {str(e)}",
                "session_id": session_id,
                "completed": False
            }
    
    # Get next set of questions (2-4 fields)
    next_questions = session_obj.get_next_questions(count=3)  # Ask about 3 fields at once
    
    if next_questions:
        if len(next_questions) == 1:
            reply = next_questions[0]
        else:
            reply = "I need a few more details:\n" + "\n".join([f"• {q}" for q in next_questions])
        
        return {
            "reply": reply,
            "session_id": session_id,
            "completed": False,
            "missing_fields": session_obj.missing_fields,
            "progress": f"{len(ESSENTIAL_FIELDS) - len(session_obj.missing_fields)}/{len(ESSENTIAL_FIELDS)} fields collected",
            "extracted_so_far": list(session_obj.extracted_data.keys())
        }
    else:
        return {
            "reply": "Please describe the case you want to report.",
            "session_id": session_id, 
            "completed": False
        }


# Utility endpoints (keep as is)
@router.post("/report/reset")
async def reset_session(session_id: str = "default"):
    """Reset a user session"""
    if session_id in user_sessions:
        del user_sessions[session_id]
    return {"message": "Session reset successfully"}

@router.get("/report/status/{session_id}")
async def get_session_status(session_id: str):
    """Get current session status"""
    if session_id in user_sessions:
        session = user_sessions[session_id]
        return {
            "extracted_fields": session.extracted_data,
            "missing_fields": session.missing_fields,
            "progress": f"{len(ESSENTIAL_FIELDS) - len(session.missing_fields)}/{len(ESSENTIAL_FIELDS)}"
        }
    return {"error": "Session not found"}











