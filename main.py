import logging
import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from models.chat_models import ChatRequest, ChatResponse
from services.travel.flight_service import FlightService
from services.travel.hotel_service import HotelService
from services.travel.activity_service import ActivityService
from services.travel.google_places_service import GooglePlacesService
from services.travel.events_service import EventService, EventDetails
from services.travel.local_search_service import LocalSearchService, PlaceDetails
from repositories.session_repository import SessionRepository
from managers.chat_manager import ChatManager
from config.settings import LOG_LEVEL, LOG_FORMAT
from typing import List, Dict, Any, Optional
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
event_service = EventService()
local_search_service = LocalSearchService()
google_places_service = GooglePlacesService()


# Define the function to get chat manager with dependency injection
def get_chat_manager(session_repository: SessionRepository = Depends(get_session_repository)):
    return ChatManager(
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
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)


# Define response model for chat history
class MessageHistoryResponse(BaseModel):
    messages: List[Dict[str, str]]


# Define request model for clearing user sessions
class ClearUserSessionsRequest(BaseModel):
    user_id: str


# Define response model for events
class EventsResponse(BaseModel):
    events: List[EventDetails]


# Define response model for local search
class LocalSearchResponse(BaseModel):
    places: List[PlaceDetails]


# Define response model for Google Places API attractions
class AttractionsResponse(BaseModel):
    attractions: List[Dict[str, Any]]


# Define response model for day trips
class DayTripsResponse(BaseModel):
    day_trips: List[Dict[str, Any]]


# Define response model for trip cost breakdown
class TripCostBreakdownResponse(BaseModel):
    currency: str
    total: float
    items: List[Dict[str, Any]]


@app.options("/chat")
async def options_chat():
    """Handle OPTIONS request for /chat endpoint"""
    return {"message": "OK"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
        request: ChatRequest,
        session_repository: SessionRepository = Depends(get_session_repository),
        chat_manager: ChatManager = Depends(get_chat_manager)
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

        # Process the message using the Chat Completions API
        try:
            result = await chat_manager.process_message(
                request.session_id,
                request.message
            )
        except Exception as e:
            logger.error(f"Error in processing message: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            result = {
                "response": "I'm having trouble processing your request. Our team has been notified of this issue.",
                "extracted_data": session_repository.get_trip_details(request.session_id).to_dict()
            }

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
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
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


@app.post("/clear-user-sessions")
async def clear_user_sessions(
        request: ClearUserSessionsRequest,
        session_repository: SessionRepository = Depends(get_session_repository)
):
    """
    Clear all sessions associated with a specific user ID

    Args:
        request: Request containing the user ID to clear sessions for

    Returns:
        Success message
    """
    try:
        user_id = request.user_id
        # Use a pattern to match all session IDs for this user
        pattern = f"user_{user_id}_*"
        cleared_count = session_repository.clear_user_sessions(pattern)

        return {
            "status": "success",
            "message": f"Successfully cleared {cleared_count} sessions for user {user_id}"
        }
    except Exception as e:
        logger.error(f"Error clearing user sessions: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear user sessions: {str(e)}"
        )


@app.get("/events/{destination}", response_model=EventsResponse)
async def get_events(destination: str):
    """
    Get upcoming events for a destination

    Args:
        destination: City or location name

    Returns:
        List of events at the destination
    """
    try:
        events = await event_service.get_events(destination)
        return {"events": events}
    except Exception as e:
        logger.error(f"Error fetching events for {destination}: {e}")
        return {"events": []}


@app.get("/trip-cost/{session_id}", response_model=TripCostBreakdownResponse)
async def get_trip_cost_breakdown(
        session_id: str,
        session_repository: SessionRepository = Depends(get_session_repository)
):
    """
    Get the trip cost breakdown for a specific session

    Args:
        session_id: Session identifier

    Returns:
        The cost breakdown for the trip
    """
    try:
        # Get cost breakdown from session repository
        cost_breakdown = session_repository.get_trip_cost_breakdown(session_id)

        # Extend session expiry on successful retrieval
        session_repository.set_session_expiry(session_id)

        return TripCostBreakdownResponse(
            currency=cost_breakdown.get("currency", "USD"),
            total=cost_breakdown.get("total", 0.0),
            items=cost_breakdown.get("items", [])
        )
    except Exception as e:
        logger.error(f"Error retrieving trip cost breakdown: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

        # Return empty breakdown if error
        return TripCostBreakdownResponse(
            currency="USD",
            total=0.0,
            items=[]
        )


@app.get("/places/{location}", response_model=LocalSearchResponse)
async def search_places(location: str, query: str = "restaurants"):
    """
    Search for local places in a specific location

    Args:
        location: The location to search in
        query: The search query (default: "restaurants")

    Returns:
        List of places matching the query in the specified location
    """
    try:
        places = await local_search_service.search_places(query, location)
        return LocalSearchResponse(places=places)
    except Exception as e:
        logger.error(f"Error searching for '{query}' in {location}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search places: {str(e)}"
        )


@app.get("/attractions/{location}", response_model=AttractionsResponse)
async def search_attractions(
        location: str,
        category: Optional[str] = None,
        radius: int = 5000
):
    """
    Search for attractions near a specific location using Google Places API

    Args:
        location: The location to search in
        category: Category of places to search for (attractions, museums, landmarks, restaurants, parks, nightlife, family-friendly)
        radius: Search radius in meters (default: 5000)

    Returns:
        List of attractions matching the query in the specified location
    """
    try:
        logger.info(f"Searching attractions in {location}, category: {category}, radius: {radius}m")
        attractions = await google_places_service.nearby_search(
            location=location,
            radius=radius,
            category=category
        )

        # Transform the attractions into a more frontend-friendly format
        result = []
        for attraction in attractions:
            # Get photo URLs safely
            photo_urls = []
            if attraction.photos:
                for photo in attraction.photos[:3]:  # Limit to 3 photos
                    if photo.photo_reference:
                        photo_url = google_places_service.get_photo_url(photo.photo_reference)
                        if photo_url:
                            photo_urls.append(photo_url)
                            logger.debug(f"Added photo URL: {photo_url}")

            # Ensure all required fields have default values if missing
            place_data = {
                "id": attraction.place_id,
                "name": attraction.name,
                "place_id": attraction.place_id,
                "rating": attraction.rating if attraction.rating else 0,
                "user_ratings_total": attraction.user_ratings_total if attraction.user_ratings_total else 0,
                "price_level": attraction.price_level if attraction.price_level else 0,
                "vicinity": attraction.vicinity if attraction.vicinity else "Address not available",
                "formatted_address": attraction.formatted_address if attraction.formatted_address else attraction.vicinity or "Address not available",
                "photos": photo_urls,
                "types": attraction.types,
                "coordinates": {
                    "latitude": attraction.geometry.location.lat,
                    "longitude": attraction.geometry.location.lng
                },
                "open_now": attraction.opening_hours.open_now if attraction.opening_hours else None
            }
            result.append(place_data)

        logger.info(f"Returning {len(result)} attractions with {sum(len(place['photos']) for place in result)} photos")
        return AttractionsResponse(attractions=result)
    except Exception as e:
        logger.error(f"Error searching attractions in {location}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search attractions: {str(e)}"
        )


@app.get("/day-trips/{origin}", response_model=DayTripsResponse)
async def find_day_trips(
        origin: str,
        radius_km: int = 150,
        min_duration: int = 30,
        max_duration: int = 180
):
    """
    Find potential day trip destinations from an origin location

    Args:
        origin: The starting location
        radius_km: Maximum search radius in kilometers (default: 150)
        min_duration: Minimum travel duration in minutes (default: 30)
        max_duration: Maximum travel duration in minutes (default: 180)

    Returns:
        List of potential day trip destinations with distance, duration, and attractions
    """
    try:
        logger.info(f"Finding day trips from {origin} with radius {radius_km}km")
        day_trips = await google_places_service.find_day_trips(
            origin=origin,
            radius_km=radius_km,
            min_duration_minutes=min_duration,
            max_duration_minutes=max_duration
        )

        # Transform the day trips into a more frontend-friendly format
        result = []
        for trip in day_trips:
            # Format attractions
            attractions = []
            for attraction in trip.top_attractions:
                # Handle photo reference safely
                photo_url = ""
                if attraction.photos and len(attraction.photos) > 0 and attraction.photos[0].photo_reference:
                    photo_url = google_places_service.get_photo_url(attraction.photos[0].photo_reference)
                    logger.debug(f"Generated attraction photo URL: {photo_url}")

                attractions.append({
                    "id": attraction.place_id,
                    "name": attraction.name,
                    "rating": attraction.rating if attraction.rating else 0,
                    "photo": photo_url,
                    "vicinity": attraction.vicinity if attraction.vicinity else f"Near {trip.name}"
                })

            # Get a photo for the destination
            destination_photo = ""
            if trip.photo_reference:
                destination_photo = google_places_service.get_photo_url(trip.photo_reference)
                logger.debug(f"Generated destination photo URL: {destination_photo}")

            trip_data = {
                "name": trip.name,
                "place_id": trip.place_id,
                "distance": trip.distance_text,
                "distance_value": trip.distance_value,
                "duration": trip.duration_text,
                "duration_value": trip.duration_value,
                "photo": destination_photo,
                "top_attractions": attractions,
                "coordinates": {
                    "latitude": trip.location.lat,
                    "longitude": trip.location.lng
                }
            }
            result.append(trip_data)

        logger.info(
            f"Returning {len(result)} day trips with {sum(len(trip['top_attractions']) for trip in result)} attractions")
        return DayTripsResponse(day_trips=result)
    except Exception as e:
        logger.error(f"Error finding day trips from {origin}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to find day trips: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)