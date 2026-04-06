import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# scraper/ 폴더를 경로에 추가 (agent_tools 등 내부 임포트 해결)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scraper"))
from agent_runner import InsuranceAgent

agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    api_key = os.environ["OPENROUTER_API_KEY"]
    agent = InsuranceAgent(api_key=api_key, load_models=True)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://insurance-project-gamma.vercel.app"],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        response = agent.chat(req.message)
        return {"content": response.content, "error": None}
    except Exception as e:
        return {"content": None, "error": str(e)}
