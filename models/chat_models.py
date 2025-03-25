from pydantic import BaseModel
from typing import Optional, Dict, Any, List, TypedDict


class ChatRequest(BaseModel):
    """Model for chat API request"""
    session_id: str
    message: str


class ChatResponse(BaseModel):
    """Model for chat API response"""
    response: str
    extracted_data: Optional[Dict[str, Any]] = None


class AgentState(TypedDict):
    destination: str
    messages: List[Dict]
    research_topics: List[str]
    research_results: Dict
    curated_content: Dict
    final_plan: Dict
    error: Optional[str]
