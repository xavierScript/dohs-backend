from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter(
    prefix="/inference",
    tags=["AI Powered Inference Authentication"]
)

@router.post("/chat")
async def chat(request: dict):
    prompt = request.get("prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    llm_endpoint = "https://dohs-ollama.fllxmx.easypanel.host/api/generate"
    payload = {
        "prompt": prompt,
        "max_tokens": 256,
        "temperature": 0.7
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(llm_endpoint, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="LLM service error.")
        data = response.json()

    return {"completion": data.get("completion") or data.get("choices", [{}])[0].get("text", "")}


