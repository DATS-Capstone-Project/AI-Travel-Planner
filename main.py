import logging
import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from models.chat_models import ChatRequest, ChatResponse
from services.travel.flight_service import FlightService
from services.travel.hotel_service import HotelService
from services.travel.activity_service import ActivityService
from repositories.session_repository import SessionRepository
from managers.assistants_manager import AssistantsManager
from config.settings import LOG_LEVEL, LOG_FORMAT
from typing import List, Dict
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT
)

logger = logging.getLogger(__name__)

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_SSL = os.getenv("REDIS_SSL", "False").lower() == "true"


# Define a function to get Redis client
def get_redis():
    redis_client = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        ssl=REDIS_SSL,
        decode_responses=False  # Keep binary responses for proper handling
    )
    try:
        yield redis_client
    finally:
        redis_client.close()


# Initialize services and repositories with dependency injection
def get_session_repository(redis: Redis = Depends(get_redis)):
    return SessionRepository(redis)


# Initialize travel services
flight_service = FlightService()
hotel_service = HotelService()
activity_service = ActivityService()


# Define the function to get assistants manager with dependency injection
def get_assistants_manager(session_repository: SessionRepository = Depends(get_session_repository)):
    return AssistantsManager(
        session_repository=session_repository,
        flight_service=flight_service,
        hotel_service=hotel_service,
        activity_service=activity_service,
        extractor_type="llm"  # Use hybrid extraction (LLM with regex fallback)
    )


app = FastAPI(title="Travel Planner API")

# Add CORS middleware with more specific configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:3000"],  # Frontend URLs
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Specify allowed methods
    allow_headers=["Content-Type", "Authorization", "Accept"],  # Specify allowed headers
    expose_headers=["Content-Type", "Authorization"],  # Headers to expose to frontend
    max_age=3600,  # Cache preflight requests for 1 hour
)


# Define response model for chat history
class MessageHistoryResponse(BaseModel):
    messages: List[Dict[str, str]]


@app.options("/chat")
async def options_chat():
    """Handle OPTIONS request for /chat endpoint"""
    return {"message": "OK"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
        request: ChatRequest,
        session_repository: SessionRepository = Depends(get_session_repository),
        assistants_manager: AssistantsManager = Depends(get_assistants_manager)
):
    """
    Process a chat message and return a response

    Args:
        request: Chat request with session_id and message

    Returns:
        Chat response with response text and extracted data
    """
    try:
        # Store user message in history
        session_repository.add_message(
            request.session_id,
            {"role": "user", "content": request.message}
        )

        # Process the message using the Assistants API
        result = await assistants_manager.process_message(
            request.session_id,
            request.message
        )

        # Store assistant response in history
        session_repository.add_message(
            request.session_id,
            {"role": "assistant", "content": result["response"]}
        )

        # Extend session expiry on successful interaction
        session_repository.set_session_expiry(request.session_id)

        return ChatResponse(
            response=result["response"],
            extracted_data=result.get("extracted_data")
        )

    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        return ChatResponse(
            response="I'm having trouble processing that. Could you please try again later?"
        )


@app.get("/chat/history/{session_id}", response_model=MessageHistoryResponse)
async def get_chat_history(
        session_id: str,
        session_repository: SessionRepository = Depends(get_session_repository)
):
    """
    Get the message history for a specific session

    Args:
        session_id: Session identifier

    Returns:
        List of messages in the session
    """
    try:
        messages = session_repository.get_message_history(session_id)
        # Extend session expiry on successful retrieval
        session_repository.set_session_expiry(session_id)
        return MessageHistoryResponse(messages=messages)
    except Exception as e:
        logger.error(f"Error retrieving chat history: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve chat history: {str(e)}"
        )


@app.options("/reset/{session_id}")
async def options_reset(session_id: str):
    """Handle OPTIONS request for /reset endpoint"""
    return {"message": "OK"}


@app.post("/reset/{session_id}")
async def reset_session(
        session_id: str,
        session_repository: SessionRepository = Depends(get_session_repository)
):
    """
    Reset a session

    Args:
        session_id: Session identifier

    Returns:
        Success message
    """
    try:
        session_repository.reset_session(session_id)
        return {"status": "success", "message": "Session reset successfully"}
    except Exception as e:
        logger.error(f"Error resetting session: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset session: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)