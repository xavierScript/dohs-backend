# agent.py
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from models.case_model import HealthCaseBase



# Request model with proper type hints and validation
class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="The prompt for the AI model")
    max_tokens: int = Field(default=256, ge=1, le=4096, description="Maximum tokens to generate")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    model: str = Field(default="deepseek-r1:1.5b", description="Model to use for inference")



OLLAMA_CHAT_URL = "https://dohs-ollama.fllxmx.easypanel.host/api/generate"   # your existing route
REPORT_SUBMIT_URL = "https://your-api.com/report/submit"   # replace with real one

async def extract_fields_from_prompt(prompt: str) -> HealthCaseBase:
    """
    Ask the model to extract the required fields from user's natural language report.
    """
    llm_endpoint = OLLAMA_CHAT_URL

    system_prompt = f"""
    You are a structured data extractor for disease reports.
    Given a user's natural language input, return a JSON object
    strictly matching this schema:

    {{
      "case_id": "string",
      "personID": "string",
      "disease": "string",
      "classification": "string",
      "outcome": "string",
      "longitude": 0,
      "latitude": 0,
      "state": "string",
      "lga": "string",
      "health_facility": "string",
      "region": "string",
      "date_of_onset": "ISO 8601 string",
      "date_of_confirmation": "ISO 8601 string",
      "reporting_source": "string",
      "age": 0,
      "sex": "string",
      "occupation": "string",
      "symptoms": "string",
      "risk_factors": "string",
      "category": "Human"
    }}

    If a field is not mentioned, set its value to null.
    Respond with **JSON only**, no explanations.
    """

    payload = {
        "model": "llama3.2:latest",
        "prompt": f"{system_prompt}\nUser: {prompt}",
        "stream": False
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(llm_endpoint, json=payload, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e}")
    except httpx.HTTPStatusError as e:
        status = getattr(e.response, "status_code", 502)
        raise HTTPException(status_code=status, detail=f"LLM returned error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error contacting LLM: {e}")

    json_str = (data.get("completion") or data.get("text") or "").strip()
    try:
        import json
        parsed = json.loads(json_str)
        return HealthCaseBase(**parsed)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON from model: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to build HealthCaseBase: {e}")


def find_missing_fields(report: HealthCaseBase):
    missing = [f for f, v in report.dict().items() if v is None]
    return missing
