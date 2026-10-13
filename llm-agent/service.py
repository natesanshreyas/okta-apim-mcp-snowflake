"""
Agent service (Pattern B backend) — the thing APIM's /agent API routes to.

Exposes POST /agent/chat. APIM has already validated the end user's Okta token
before this is reached; the user's bearer token is forwarded so the agent can use
it as the subject of the OBO token exchange (see obo.py).

Run locally:
    uvicorn service:app --host 0.0.0.0 --port 8081

Deploy as an Azure Container App / App Service with managed identity + Key Vault
for OKTA_AGENT_CLIENT_SECRET and AZURE_OPENAI_API_KEY.
"""

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from agent_core import run_agent

app = FastAPI(title="MCP Snowflake Agent", version="1.0.0")


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str


@app.get("/agent/health")
def health():
    return {"status": "ok"}


@app.post("/agent/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
    # APIM forwards the validated user token; we need it for the OBO exchange.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing user bearer token")
    user_token = authorization.split(" ", 1)[1].strip()

    try:
        answer = await run_agent(req.question, user_token)
    except Exception as e:  # surface config/OBO/model errors as 502
        raise HTTPException(status_code=502, detail=f"Agent error: {e}") from e
    return ChatResponse(answer=answer)
