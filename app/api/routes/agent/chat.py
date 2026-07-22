from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx

router = APIRouter(
    prefix="/inference",
    tags=["AI Powered Inference Authentication"]
)

# Request model with proper type hints and validation
class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="The prompt for the AI model")
    max_tokens: int = Field(default=256, ge=1, le=4096, description="Maximum tokens to generate")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    model: str = Field(default="deepseek-r1:1.5b", description="Model to use for inference")

# Response model
class ChatResponse(BaseModel):
    completion: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Generate AI completion using Ollama endpoint
    
    - **prompt**: The input prompt (required)
    - **max_tokens**: Maximum number of tokens to generate (default: 256)
    - **temperature**: Controls randomness (0.0 = deterministic, 2.0 = very random)
    - **model**: Which model to use (default: deepseek-r1:1.5b)
    """
    
    llm_endpoint = "https://dohs-ollama.fllxmx.easypanel.host/api/generate"
    
    # Ollama payload structure
    payload = {
        "model": request.model,
        "prompt": request.prompt,
        "stream": False,
        "options": {
            "temperature": request.temperature,
            "num_predict": request.max_tokens  # Ollama uses num_predict
        }
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(llm_endpoint, json=payload)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code, 
                    detail=f"LLM service error: {response.text}"
                )
            
            data = response.json()
            
            # Extract response from Ollama's structure
            completion_text = data.get("response", "")
            
            return ChatResponse(
                completion=completion_text,
                model=request.model,
                prompt_tokens=data.get("prompt_eval_count"),
                completion_tokens=data.get("eval_count")
            )
                
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="LLM service timeout")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {str(e)}")