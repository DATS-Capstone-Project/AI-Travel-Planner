import logging
from fastapi import FastAPI, HTTPException
from models.chat_models import ChatRequest, ChatResponse
from services.travel.flight_service import FlightService
from services.travel.hotel_service import HotelService
from services.travel.activity_service import ActivityService
from repositories.session_repository import SessionRepository
from managers.assistants_manager import AssistantsManager
from config.settings import LOG_LEVEL, LOG_FORMAT

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT
)

logger = logging.getLogger(__name__)

# Initialize services and repositories
session_repository = SessionRepository()
flight_service = FlightService()
hotel_service = HotelService()
activity_service = ActivityService()

# Initialize assistants manager with hybrid extraction
assistants_manager = AssistantsManager(
    session_repository=session_repository,
    flight_service=flight_service,
    hotel_service=hotel_service,
    activity_service=activity_service,
    extractor_type="hybrid"  # Use hybrid extraction (LLM with regex fallback)
)

app = FastAPI(title="Travel Planner API")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a chat message and return a response

    Args:
        request: Chat request with session_id and message

    Returns:
        Chat response with response text and extracted data
    """
    try:
        # Process the message using the Assistants API
        result = await assistants_manager.process_message(
            request.session_id,
            request.message
        )

        return ChatResponse(
            response=result["response"],
            extracted_data=result.get("extracted_data")
        )

    except Exception as e:
        logger.error(f"Error processing chat request: {e}")
        return ChatResponse(
            response="I'm having trouble processing that. Could you please try again later?"
        )


@app.post("/reset/{session_id}")
async def reset_session(session_id: str):
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