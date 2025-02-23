from pydantic import BaseModel
from typing import Optional


class TripDetails(BaseModel):
    destination: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    travelers: Optional[int] = None
    budget: Optional[int] = None
    preferences: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    response: str
