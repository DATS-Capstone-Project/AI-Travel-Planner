import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
import re

from openai import OpenAI
from config.settings import OPENAI_API_KEY, CONVERSATION_MODEL
from repositories.session_repository import SessionRepository
from services.extraction.extractor_factory import ExtractorFactory
from services.travel.activity_service import ActivityService
from services.travel.flight_service import FlightService
from services.travel.hotel_service import HotelService
from services.supervisors.travel_supervisor import TravelSupervisor
from models.trip_details import TripDetails
from services.customizers.customizer_agent import CustomizerAgent

# Configure logger
logger = logging.getLogger(__name__)


class ChatManager:
    """Manager for OpenAI Chat Completions API interactions"""

    def __init__(
            self,
            session_repository: SessionRepository,
            flight_service: FlightService,
            hotel_service: HotelService,
            activity_service: ActivityService,
            extractor_type: str = "llm",
            model: str = CONVERSATION_MODEL
    ):
        """
        Initialize the chat manager.
        """
        self.client = OpenAI(api_key=OPENAI_API_KEY)

        self.session_repository = session_repository
        self.flight_service = flight_service
        self.hotel_service = hotel_service
        self.activity_service = activity_service
        self.extractor = ExtractorFactory.create_extractor(extractor_type)
        self.model = model

        # Initialize the supervisor and customizer
        self.travel_supervisor = TravelSupervisor(
            flight_service=flight_service,
            hotel_service=hotel_service,
            activity_service=activity_service
        )
        self.customizer_agent = CustomizerAgent(hotel_service=hotel_service)

        self.system_prompt = """
            You are a helpful travel planning assistant. 
            Help users plan trips by gathering information about:
            - origin (REQUIRED)
            - destination (REQUIRED)
            - start date (REQUIRED)
            - end date (REQUIRED)
            - number of travelers (REQUIRED)
            - budget (OPTIONAL)
            - activity preferences (OPTIONAL)

            IMPORTANT WORKFLOW:
            1. COLLECTION PHASE: 
              - Review the trip details provided to see what information you already have
              - DO NOT ask for information that has already been provided
              - Focus on collecting missing REQUIRED fields first
              - Then try to collect OPTIONAL fields

            2. CONFIRMATION PHASE:
              - Once all required fields are collected, summarize the trip details
              - Ask the user to confirm if everything is correct

            3. PLANNING PHASE:
              - After user confirms, proceed with planning the itinerary
            4. FOLLOW-UP PHASE:
                - If the user asks for changes or has follow-up questions, handle them accordingly
                -If the user asks for hotel customization, handle it separately
                - If the user asks for a day-by-day itinerary, generate it with the customized hotels, flights, and activities
                
            
            

            CRITICAL: Always check what information you already have before asking questions.
            This ensures a much better user experience.
        """

    async def process_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """
        Process a user message using the Chat Completions API.
        """
        logger.info(f"Processing message for session {session_id}")
        logger.info(f"User message: {message}")

        # Check if this is an itinerary generation request
        itinerary_keywords = ["create itinerary", "make itinerary", "plan my days", "day by day plan"]
        if any(keyword in message.lower() for keyword in itinerary_keywords):
            trip_details = self.session_repository.get_trip_details(session_id)
            if not trip_details.get("selected_hotel"):
                return {
                    "response": "Please select a hotel first before I create your itinerary. Would you like to see hotel options?",
                    "extracted_data": trip_details.to_dict()
                }
            return await self._generate_itinerary(session_id, trip_details)

        # Check if this is a hotel customization request
        hotel_keywords = ["customize hotel", "change hotel", "different hotel", "hotel preference", 
                         "hotel option", "hotel amenities", "hotel location", "hotel price"]
        if any(keyword in message.lower() for keyword in hotel_keywords):
            return await self.handle_hotel_customization(session_id, message)

        # Get trip details
        existing_trip_details = self.session_repository.get_trip_details(session_id)

        # Extract entities from the message
        extracted_details = self.extractor.extract(message, existing_details=existing_trip_details)
        logger.info(f"Extracted details: {extracted_details.to_dict()}")

        # Warn if origin is still missing
        if not extracted_details.origin:
            logger.warning("Origin is missing from extracted details. Please ask the user for the departure city.")

        # Update session data with extracted details
        self.session_repository.update_trip_details(session_id, extracted_details.to_dict())

        # Get updated trip details
        trip_details = self.session_repository.get_trip_details(session_id)
        trip_dict = trip_details.to_dict()

        # If you have date validations in your business logic, handle them here
        if trip_dict.get("start_date") == "Error" or trip_dict.get("end_date") == "Error":
            return {
                "response": "Please ensure your start date and end date are valid and within the next 6 months.",
                "extracted_data": trip_dict
            }

        # Determine missing fields
        missing_required = trip_details.missing_required_fields()
        missing_optional = trip_details.missing_optional_fields()

        logger.info(f"Trip details ready for confirmation: {trip_details.is_ready_for_confirmation()}")
        logger.info(f"Missing required fields: {missing_required}")
        logger.info(f"Missing optional fields: {missing_optional}")

        # Check if we're already in supervisor mode (already generated an itinerary)
        has_itinerary = self.session_repository.has_itinerary(session_id)
        if has_itinerary:
            # Handle follow-up questions after itinerary generation
            return await self._handle_followup_question(session_id, message, trip_details)

        # Check for user confirmation + whether we have all required fields
        if self._check_confirmation(message) and trip_details.is_ready_for_confirmation():
            logger.info("User confirmed with all required fields present.")
            self.session_repository.set_confirmed(session_id, True)

            # Generate initial itinerary
            return await self._generate_itinerary(session_id, trip_details)
        elif self._check_confirmation(message) and not trip_details.is_ready_for_confirmation():
            logger.warning(f"User tried to confirm but missing required fields: {missing_required}")
            # Don't set confirmation; continue collecting data

        # Create context message based on current trip details
        context_msg = self._create_context_message(trip_details, missing_required, missing_optional)

        # Get message history (limited to last 10 messages)
        message_history = self.session_repository.get_message_history(session_id)
        messages = []

        # Add system prompt and context
        messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "system", "content": context_msg})

        # Add conversation history
        for msg in message_history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Add current user message
        messages.append({"role": "user", "content": message})

        # Call Chat Completions API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )

            assistant_message = response.choices[0].message.content
            logger.info(f"Assistant response: {assistant_message}")

            return {
                "response": assistant_message,
                "extracted_data": trip_details.to_dict()
            }
        except Exception as e:
            logger.error(f"Error calling OpenAI Chat API: {e}")
            return {
                "response": "I'm having trouble processing your request right now. Could you please try again?",
                "extracted_data": trip_details.to_dict()
            }

    def _check_confirmation(self, message: str) -> bool:
        """Check if the message contains a confirmation."""
        confirmation_keywords = [
            "yes", "yeah", "yep", "sure", "ok", "okay", "proceed",
            "confirm", "book", "go ahead", "sounds good", "please"
        ]

        message_lower = message.lower().strip()

        # Log the message being checked for confirmation
        logger.info(f"Checking message for confirmation: '{message_lower}'")

        # Special case for common phrases
        if message_lower in ["yes", "yes please", "yes, please", "sure", "ok", "okay", "proceed", "go ahead"]:
            logger.info(f"Direct match found for confirmation: '{message_lower}'")
            return True

        # Check for negative responses that include confirmation keywords
        negation_before_confirmation = any(
            neg + " " + conf in message_lower
            for neg in ["don't", "do not", "cannot", "can't", "not"]
            for conf in confirmation_keywords
        )
        if negation_before_confirmation:
            logger.info(f"Negation before confirmation detected: '{message_lower}'")
            return False

        # Check for positive confirmation
        has_confirmation = any(keyword in message_lower.split() for keyword in confirmation_keywords)
        logger.info(f"Has confirmation keyword: {has_confirmation}")

        # Look for negation
        has_negation = any(word in message_lower.split() for word in ["no", "nope", "don't", "not", "cancel"])
        logger.info(f"Has negation: {has_negation}")

        result = has_confirmation and not has_negation
        logger.info(f"Confirmation result for '{message_lower}': {result}")
        return result

    def _create_context_message(self, trip_details: TripDetails,
                                missing_required: List[str],
                                missing_optional: List[str]) -> str:
        """Create a context message about current trip information and missing fields."""
        context_msg = "Current trip information:\n"
        for key, value in trip_details.__dict__.items():
            if value is not None and key != 'confidence_levels':
                context_msg += f"✓ {key}: {value}\n"

        if missing_required or missing_optional:
            context_msg += "\nMISSING INFORMATION:"
            if missing_required:
                context_msg += "\nRequired (must collect):\n"
                for field in missing_required:
                    context_msg += f"⚠️ {field}\n"
            if missing_optional:
                context_msg += "\nOptional (should try to collect):\n"
                for field in missing_optional:
                    context_msg += f"○ {field}\n"
            context_msg += "\nPlease focus on collecting the missing required information first."
        else:
            context_msg += "\n✓ All required and optional fields have been collected. You can now confirm the details with the user."

        context_msg += "\n\nIMPORTANT: Use this information to avoid asking for details that have already been provided. Focus on collecting missing required fields."

        return context_msg

    async def _generate_itinerary(self, session_id: str, trip_details: TripDetails) -> Dict[str, Any]:
        """Generate a complete travel itinerary using the supervisor agent."""
        logger.info(f"Generating itinerary for session {session_id}")
        logger.info(f"Trip details: {trip_details.to_dict()}")

        try:
            # Call the travel supervisor to plan the trip
            supervisor_result = await self.travel_supervisor.plan_trip(
                session_id=session_id,
                trip_details=trip_details
            )

            logger.info(f"Supervisor completed planning")

            # Extract the itinerary from the result
            itinerary = supervisor_result.get("itinerary",
                                              "I've created your travel plan based on your preferences.")

            # Store the itinerary in the session repository
            self.session_repository.set_itinerary(session_id, itinerary)

            return {
                "response": itinerary,
                "extracted_data": trip_details.to_dict()
            }
        except Exception as e:
            logger.error(f"Error in travel supervisor: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

            return {
                "response": "I'm sorry, but I encountered an error while planning your trip. Please try again.",
                "extracted_data": trip_details.to_dict()
            }

    async def _handle_followup_question(self, session_id: str, message: str, trip_details: TripDetails) -> Dict[
        str, Any]:
        """Handle follow-up questions after an itinerary has been generated."""
        logger.info(f"Handling follow-up question for session {session_id}")

        # Get the stored itinerary
        itinerary = self.session_repository.get_itinerary(session_id)

        # Create a prompt for the follow-up
        prompt = f"""
        You are an expert travel planning assistant with deep knowledge of destinations worldwide. You previously generated an itinerary for a trip with these details:

        Trip Details:
        - Origin: {trip_details.origin}
        - Destination: {trip_details.destination}
        - Start Date: {trip_details.start_date}
        - End Date: {trip_details.end_date}
        - Number of Travelers: {trip_details.travelers}
        - Budget: ${trip_details.budget if trip_details.budget else 'Not specified'}
        - Preferences: {trip_details.preferences if trip_details.preferences else 'Not specified'}

        Previous Itinerary:
        {itinerary}

        The user is now asking: "{message}"

        If they're requesting a day-by-day breakdown, create a detailed daily itinerary following these guidelines:
        1. Use the following format for each day for the number of days in the trip:
        2. Include a detailed itinerary for each day, including morning, afternoon, and evening activities.
        3. For the first day,the itenary should start from whatever time the user arrives at the destination. Based on the flight selected.
        4. For the last day, the itinerary should end at the time of check-out from the hotel and based on the user's return flight.
        
        1. FORMAT FOR EACH DAY:
        ```
        DAY X - [Day of Week, Date]
        
        Morning (Time slots with specific hours):
        - [Activity/Location] (Duration)
          • Description and highlights
          • Practical tips (opening hours, tickets needed, etc.)
          • Transportation method and time
          • Estimated costs
        
        Afternoon:
        [Same structure as morning]
        
        Evening:
        [Same structure as morning]
        
        Meals:
        • Breakfast: [Suggestion with cuisine type and price range]
        • Lunch: [Suggestion with cuisine type and price range]
        • Dinner: [Suggestion with cuisine type and price range]
        
        Daily Tips:
        • Weather considerations
        • What to bring
        • Local customs or etiquette
        • Money-saving tips
        ```

        2. IMPORTANT CONSIDERATIONS:
        - Prioritize user preferences and budget
        - Include a mix of activities (cultural, leisure, adventure)
        - Give Detail itenary for each day of the trip starting from check-in to check-out
        -include flight details if applicable and hotel check-in/check-out times
        
        - Account for travel time between activities
        - Consider opening hours of attractions
        - Balance the schedule (not too packed or too light)
        - Include meal times at logical intervals
        - Factor in rest periods for longer trips
        - Account for jet lag on first day
        - Consider local customs and siesta times if applicable
        - Include alternative indoor activities for bad weather
        - Suggest photo opportunities and best times
        
        3. PRACTICAL DETAILS:
        - Include specific meeting points
        - Mention booking requirements
        - Add estimated costs for activities
        - Specify transportation methods
        - Note important phone numbers or websites
        - Include local emergency contacts
        
        4. LOCAL INSIGHTS:
        - Best times to visit attractions
        - Local festivals or events during stay
        - Hidden gems and local favorites
        - Cultural etiquette tips
        - Safety considerations
        
        5. FLEXIBILITY:
        - Suggest alternative activities
        - Provide rainy day options
        - Include free time for spontaneous exploration
        - Note which activities need advance booking

        If they want to modify aspects of the itinerary:
        1. Understand their specific modification request
        2. Suggest appropriate changes while maintaining the flow
        3. Consider impact on other activities
        4. Provide alternatives if original suggestions aren't suitable
        5. Explain reasoning for suggested modifications

        Maintain a friendly, conversational tone while providing detailed, practical information. Focus on creating a balanced, enjoyable experience that matches their preferences and travel style.
        """

        # Call the Chat Completions API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.7,
                max_tokens=2000
            )

            followup_response = response.choices[0].message.content
            logger.info(f"Follow-up response generated")
            logger.info(f"Follow-up response content: {followup_response[:100]}...")  # Log first 100 chars of response

            # If this is a substantial modification to the itinerary, update the stored itinerary
            if "day-by-day" in message.lower() or "detailed" in message.lower():
                self.session_repository.set_itinerary(session_id, followup_response)

            return {
                "response": followup_response,
                "extracted_data": trip_details.to_dict()
            }
        except Exception as e:
            logger.error(f"Error handling follow-up question: {e}")

            return {
                "response": "I'm sorry, but I encountered an error while processing your question. Could you please try again?",
                "extracted_data": trip_details.to_dict()
            }

    async def handle_hotel_customization(self, session_id: str, message: str) -> Dict[str, Any]:
        """Handle hotel customization requests from users"""
        logger.info(f"Processing hotel customization request for session {session_id}")
        
        try:
            # Get current trip details
            trip_details = self.session_repository.get_trip_details(session_id)
            
            # Prepare state for customization
            state = {
                "session_id": session_id,
                "trip_details": trip_details.to_dict(),
                "message": message
            }
            
            # Process the customization request
            result = await self.customizer_agent.customize_trip(state, "hotel")
            
            if result["status"] == "success":
                # If we have a selected hotel, update trip details
                if "selected_hotel" in result:
                    updated_trip_details = {
                        **trip_details.to_dict(),
                        "selected_hotel": result["selected_hotel"]
                    }
                    self.session_repository.update_trip_details(session_id, updated_trip_details)
                    trip_details = self.session_repository.get_trip_details(session_id)

                # If customization requires new itinerary, generate it
                if result.get("needs_new_itinerary", False):
                    # Update trip details if needed
                    if "trip_details" in result:
                        self.session_repository.update_trip_details(session_id, result["trip_details"])
                        trip_details = self.session_repository.get_trip_details(session_id)
                    
                    # Generate new itinerary
                    new_itinerary = await self._generate_itinerary(session_id, trip_details)
                    return new_itinerary
                
                # If no new itinerary needed, return the customization response
                return {
                    "response": result["message"],
                    "extracted_data": trip_details.to_dict()
                }
            else:
                return {
                    "response": result["message"],
                    "extracted_data": trip_details.to_dict()
                }
                
        except Exception as e:
            logger.error(f"Error in hotel customization: {str(e)}")
            return {
                "response": "I encountered an error while customizing your hotel preferences. Please try again.",
                "extracted_data": trip_details.to_dict() if 'trip_details' in locals() else {}
            }