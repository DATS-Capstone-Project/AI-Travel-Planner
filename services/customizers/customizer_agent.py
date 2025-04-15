import logging
from typing import Dict, Any, Optional, List
import re
from datetime import datetime
from langchain_openai import ChatOpenAI

from models.trip_details import TripDetails
from services.travel.hotel_service import HotelService

CUSTOMIZER_AGENT_PROMPT = """
You are an expert travel customization assistant, specialized in refining and personalizing travel plans. Your role is to understand user preferences and help modify their travel arrangements intelligently.

CUSTOMIZATION TYPES AND CRITERIA:

1. HOTEL CUSTOMIZATION
Analyze requests for:
- Price Range:
  * "cheaper", "budget-friendly", "affordable" → Lower price
  * "luxury", "high-end", "upscale" → Higher price
  * "mid-range", "moderate" → Middle price
- Location Preferences:
  * City center/downtown proximity
  * Beach/waterfront access
  * Near attractions/landmarks
  * Quiet/residential areas
- Amenities Required:
  * Pool, spa, gym
  * Restaurant, room service
  * Business facilities
  * Family-friendly features
- Property Type:
  * Boutique hotel
  * Resort
  * Apartment
  * Business hotel

RESPONSE FORMAT:
1. Acknowledge the customization request
2. List understood preferences
3. Present alternatives with reasoning
4. Provide clear next steps
"""

class CustomizerAgent:
    """Agent responsible for handling customization requests for travel plans"""

    def __init__(self, hotel_service: HotelService):
        """Initialize the customizer agent"""
        self.hotel_service = hotel_service
        self.logger = logging.getLogger(__name__)
        self.llm = ChatOpenAI(temperature=0.7)

    async def customize_trip(self, state: Dict[str, Any], customization_type: str) -> Dict[str, Any]:
        """Main entry point for customization requests"""
        try:
            self.logger.info(f"Starting {customization_type} customization")

            session_id = state.get("session_id")
            trip_details = state.get("trip_details", {})
            message = state.get("message", "")

            if not session_id:
                raise ValueError("Session ID is required for customization")

            # First, use LLM to understand the request
            understanding = await self._understand_request(message, customization_type)

            if customization_type == "hotel":
                return await self._handle_hotel_customization(
                    session_id=session_id,
                    message=message,
                    trip_details=trip_details,
                    understood_preferences=understanding
                )
            else:
                return {
                    "status": "error",
                    "message": f"Unsupported customization type: {customization_type}"
                }

        except Exception as e:
            self.logger.error(f"Error in customize_trip: {str(e)}")
            return {
                "status": "error",
                "message": f"Customization failed: {str(e)}"
            }

    async def _understand_request(self, message: str, customization_type: str) -> Dict[str, Any]:
        """Use LLM to understand the customization request"""
        try:
            # Check if this is a hotel selection request
            selection_keywords = ["select", "choose", "book", "want", "prefer", "take", "go with"]
            message_lower = message.lower()
            
            if any(keyword in message_lower for keyword in selection_keywords):
                # Extract hotel name from the message
                hotel_name = None
                message_parts = message_lower.split()
                for i, word in enumerate(message_parts):
                    if word in selection_keywords and i + 1 < len(message_parts):
                        # Try to find the hotel name after the selection keyword
                        hotel_name = " ".join(message_parts[i + 1:])
                        break
                
                if hotel_name:
                    return {
                        "type": "selection",
                        "hotel_name": hotel_name
                    }

            # If not a selection request, process as a customization request
            messages = [
                {"role": "system", "content": CUSTOMIZER_AGENT_PROMPT},
                {"role": "user", "content": f"Analyze this {customization_type} customization request and extract preferences: {message}"}
            ]
            
            response = await self.llm.agenerate(messages=[messages])
            # Process the response to extract preferences
            return {"type": "customization", "preferences": self._extract_hotel_preferences(message)}
            
        except Exception as e:
            self.logger.error(f"Error understanding request: {str(e)}")
            return {}

    def _parse_llm_understanding(self, llm_response: str) -> Dict[str, Any]:
        """Parse LLM response into structured preferences"""
        preferences = {}

        # Extract price preferences
        if any(phrase in llm_response.lower() for phrase in ["lower price", "budget", "affordable"]):
            preferences["price_preference"] = "lower"
        elif any(phrase in llm_response.lower() for phrase in ["luxury", "high-end", "upscale"]):
            preferences["price_preference"] = "higher"

        # Extract location preferences
        if any(phrase in llm_response.lower() for phrase in ["city center", "downtown", "central"]):
            preferences["location_preference"] = "city_center"
        elif any(phrase in llm_response.lower() for phrase in ["beach", "waterfront", "coastal"]):
            preferences["location_preference"] = "beach"

        # Extract amenities
        amenities = []
        amenity_keywords = ["pool", "spa", "gym", "restaurant", "wifi", "parking"]
        for amenity in amenity_keywords:
            if amenity in llm_response.lower():
                amenities.append(amenity)
        if amenities:
            preferences["amenities"] = amenities

        return preferences

    async def _handle_hotel_customization(self, session_id: str, message: str,
                                        trip_details: Dict[str, Any],
                                        understood_preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Handle hotel-specific customization requests"""
        try:
            self.logger.info(f"Processing hotel customization for session {session_id}")

            # Check if this is a selection request
            if understood_preferences.get("type") == "selection":
                hotel_name = understood_preferences.get("hotel_name")
                if hotel_name:
                    selected_hotel = self.hotel_service.get_hotel_by_name(session_id, hotel_name)
                    if selected_hotel:
                        return {
                            "status": "success",
                            "needs_new_itinerary": False,  # Don't automatically generate itinerary
                            "selected_hotel": selected_hotel,
                            "trip_details": {
                                **trip_details,
                                "selected_hotel": selected_hotel
                            },
                            "message": f"I've selected {selected_hotel['name']} for your stay. Here's a summary of your selection:\n\n" +
                                     f"🏨 Hotel: {selected_hotel['name']}\n" +
                                     f"⭐ Rating: {selected_hotel['rating']} ({selected_hotel['reviews']} reviews)\n" +
                                     f"💰 Price per night: {selected_hotel['price_per_night']}\n" +
                                     f"📍 Location: {selected_hotel['location']['address']}\n" +
                                     f"✨ Amenities: {', '.join(selected_hotel['amenities'][:5])}\n\n" +
                                     f"Would you like me to create a day-by-day itinerary for your trip? Just say 'yes' or 'create itinerary' if you'd like one."
                        }
                    else:
                        return {
                            "status": "error",
                            "message": f"I couldn't find the hotel '{hotel_name}' in the available options. Please try again with a hotel from the list I provided."
                        }

            # If not a selection request, handle as a customization request
            # Combine understood preferences with extracted preferences
            preferences = understood_preferences.get("preferences", {})
            if not preferences:
                preferences = self._extract_hotel_preferences(message)

            # Get alternative hotels based on preferences
            alternative_hotels = await self.hotel_service.get_alternative_hotels(
                session_id=session_id,
                destination=trip_details.get("destination"),
                checkin_date=trip_details.get("start_date"),
                checkout_date=trip_details.get("end_date"),
                adults=trip_details.get("travelers"),
                total_budget=trip_details.get("budget"),
                preferences=preferences
            )

            if not alternative_hotels:
                return {
                    "status": "error",
                    "message": "I couldn't find any hotels matching your preferences. Would you like to try different criteria?"
                }

            # Format the response using LLM
            messages = [
                {"role": "system", "content": CUSTOMIZER_AGENT_PROMPT},
                {"role": "user", "content": f"""
                    Please format a response for the user with these hotel options and preferences:
                    
                    Preferences: {preferences}
                    Hotels: {alternative_hotels}
                    
                    Follow the response format specified in the prompt.
                    End the response with: "Which hotel would you like to select? Just mention the hotel name or number from the list above."
                """}
            ]

            response = await self.llm.agenerate(messages=[messages])
            formatted_response = response.generations[0][0].text

            return {
                "status": "success",
                "needs_new_itinerary": False,  # Don't automatically generate itinerary
                "hotels": alternative_hotels,
                "trip_details": trip_details,
                "message": formatted_response
            }

        except Exception as e:
            self.logger.error(f"Error in hotel customization: {str(e)}")
            return {
                "status": "error",
                "message": f"Hotel customization failed: {str(e)}"
            }

    def _extract_hotel_preferences(self, message: str) -> Dict[str, Any]:
        """Extract hotel preferences from user message"""
        preferences = {}
        message_lower = message.lower()

        # Price preferences
        if any(word in message_lower for word in ["cheaper", "budget", "less expensive", "affordable"]):
            preferences["price_preference"] = "lower"
        elif any(word in message_lower for word in ["luxury", "expensive", "high-end", "upscale"]):
            preferences["price_preference"] = "higher"

        # Location preferences
        if any(phrase in message_lower for phrase in [
            "city center", "downtown", "central", "heart of the city",
            "city centre", "near attractions", "central location","airport","public transport"
        ]):
            preferences["location_preference"] = "city_center"
        elif any(word in message_lower for word in ["beach", "oceanfront", "seaside", "coastal"]):
            preferences["location_preference"] = "beach"

        # Amenities
        amenities = []
        amenity_keywords = {
            "pool": ["pool", "swimming"],
            "spa": ["spa", "massage", "wellness"],
            "gym": ["gym", "fitness center", "workout"],
            "restaurant": ["restaurant", "dining"],
            "wifi": ["wifi", "internet", "wireless"],
            "parking": ["parking", "garage"]
        }

        for amenity, keywords in amenity_keywords.items():
            if any(keyword in message_lower for keyword in keywords):
                amenities.append(amenity)

        if amenities:
            preferences["amenities"] = amenities

        return preferences 