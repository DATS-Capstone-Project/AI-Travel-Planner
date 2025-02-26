from pydantic import BaseModel
from typing import Optional, Dict, Any


class ChatRequest(BaseModel):
    """Model for chat API request"""
    session_id: str
    message: str


class ChatResponse(BaseModel):
    """Model for chat API response"""
    response: str
    extracted_data: Optional[Dict[str, Any]] = None