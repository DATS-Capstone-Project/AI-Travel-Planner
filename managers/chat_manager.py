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

            # Extract the budget breakdown from the itinerary
            budget_breakdown = self._extract_budget_breakdown(itinerary)

            # Store the itinerary in the session repository
            self.session_repository.set_itinerary(session_id, itinerary)

            # Store the budget breakdown if extracted successfully
            if budget_breakdown:
                self.session_repository.set_trip_cost_breakdown(session_id, budget_breakdown)

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

    def _extract_budget_breakdown(self, itinerary: str) -> Dict[str, Any]:
        """Extract budget breakdown from the itinerary text with improved pattern matching."""
        try:
            logger.info("Attempting to extract budget breakdown from itinerary")

            # Check if the budget breakdown section exists
            if "budget breakdown" not in itinerary.lower() and "estimated costs" not in itinerary.lower():
                logger.info("No budget breakdown found in itinerary")
                return None

            # Initialize variables for extraction
            budget_items = []
            total_cost = 0
            currency = "USD"  # Default currency

            # Dictionary of common budget categories with descriptions
            descriptions = {
                "flight": "Round-trip airfare between origin and destination cities.",
                "flights": "Round-trip airfare between origin and destination cities.",
                "flight (per traveler)": "Round-trip airfare per person between origin and destination cities.",
                "flights (per traveler)": "Round-trip airfare per person between origin and destination cities.",
                "hotel": "Accommodation costs for the entire stay.",
                "hotels": "Accommodation costs for the entire stay.",
                "lodging": "Accommodation costs for the entire stay.",
                "accommodation": "Accommodation costs for the entire stay.",
                "accommodations": "Accommodation costs for the entire stay.",
                "food": "Estimated food and dining expenses for the trip duration.",
                "meals": "Estimated food and dining expenses for the trip duration.",
                "dining": "Estimated food and dining expenses for the trip duration.",
                "food (approx. per day)": "Estimated daily food and dining expenses.",
                "activities": "Costs for sightseeing, tours, attractions, and entertainment.",
                "attractions": "Costs for sightseeing, tours, and entertainment venues.",
                "entertainment": "Costs for attractions, shows, and entertainment activities.",
                "transport": "Local transportation expenses including taxis, public transit, and ride shares.",
                "transportation": "Local transportation expenses including taxis, public transit, and ride shares.",
                "local transportation": "Transportation expenses within the destination including taxis and public transit.",
                "car rental": "Vehicle rental costs for the duration of the trip.",
                "shopping": "Estimated expenses for souvenirs and personal shopping.",
                "souvenirs": "Estimated expenses for mementos and gifts.",
                "miscellaneous": "Additional expenses not covered in other categories."
            }

            # Try to extract using markdown table format first (most common)
            table_pattern = r"\| *([^|]+) *\| *\$?([\d,\.]+) *\|"
            table_matches = re.findall(table_pattern, itinerary)

            if table_matches:
                logger.info(f"Found {len(table_matches)} budget items in table format")

                # Extract items - filter out header rows and total row
                for item, amount in table_matches:
                    item = item.strip()
                    # Skip the header row and the total row
                    if (item.lower() == "item" or
                            "total" in item.lower() or
                            "estimated cost" in item.lower() or
                            "---" in item):
                        continue

                    # Clean the amount and convert to float
                    cleaned_amount = amount.replace(',', '').strip()
                    try:
                        float_amount = float(cleaned_amount)
                        # Add description based on category
                        description = ""
                        item_lower = item.lower()
                        for key, desc in descriptions.items():
                            if key in item_lower:
                                description = desc
                                break

                        budget_items.append({
                            "category": item,
                            "amount": float_amount,
                            "description": description
                        })
                    except ValueError:
                        logger.warning(f"Could not convert amount '{amount}' to float")

                # Try to extract total specifically
                total_pattern = r"\| *\*?\*?(?:Total|TOTAL|Total Estimated Cost)\*?\*? *\| *\*?\*?\$?([\d,\.]+)\*?\*? *\|"
                total_match = re.search(total_pattern, itinerary)

                if total_match:
                    total_cost = float(total_match.group(1).replace(',', ''))
                    logger.info(f"Found total cost: ${total_cost}")
                else:
                    # Calculate total from items if explicit total not found
                    total_cost = sum(item["amount"] for item in budget_items)
                    logger.info(f"Calculated total cost from items: ${total_cost}")

            # If no table format found, try bullet or list format
            elif not budget_items:
                # Look for bullet points or numbered lists with costs
                list_pattern = r"[-*•]\s+([^:$]+):\s+\$?([\d,\.]+)"
                list_matches = re.findall(list_pattern, itinerary)

                if list_matches:
                    logger.info(f"Found {len(list_matches)} budget items in list format")
                    for item, amount in list_matches:
                        cleaned_amount = amount.replace(',', '').strip()
                        try:
                            float_amount = float(cleaned_amount)
                            # Add description based on category
                            description = ""
                            item_lower = item.lower().strip()
                            for key, desc in descriptions.items():
                                if key in item_lower:
                                    description = desc
                                    break

                            budget_items.append({
                                "category": item.strip(),
                                "amount": float_amount,
                                "description": description
                            })
                        except ValueError:
                            logger.warning(f"Could not convert amount '{amount}' to float")

                    # Try to find total in text
                    total_pattern = r"Total(?:\s+Estimated)?\s+Cost:?\s+\$?([\d,\.]+)"
                    total_match = re.search(total_pattern, itinerary, re.IGNORECASE)

                    if total_match:
                        total_cost = float(total_match.group(1).replace(',', ''))
                    else:
                        # Calculate total from items
                        total_cost = sum(item["amount"] for item in budget_items)

            # Try another common format: key-value pairs
            elif not budget_items:
                pair_pattern = r"([^:]+):\s+\$?([\d,\.]+)"
                pair_matches = re.findall(pair_pattern, itinerary)

                if pair_matches:
                    logger.info(f"Found {len(pair_matches)} budget items in key-value format")
                    for item, amount in pair_matches:
                        item_lower = item.lower().strip()
                        # Skip if it's not likely a budget item
                        if ("total" in item_lower and "cost" in item_lower) or item_lower == "budget":
                            continue

                        if any(word in item_lower for word in
                               ["flight", "hotel", "food", "activities", "transport", "activities", "dining"]):
                            cleaned_amount = amount.replace(',', '').strip()
                            try:
                                float_amount = float(cleaned_amount)
                                # Add description based on category
                                description = ""
                                for key, desc in descriptions.items():
                                    if key in item_lower:
                                        description = desc
                                        break

                                budget_items.append({
                                    "category": item.strip(),
                                    "amount": float_amount,
                                    "description": description
                                })
                            except ValueError:
                                continue

                    # Look for total cost
                    total_pattern = r"Total(?:\s+Estimated)?\s+Cost:?\s+\$?([\d,\.]+)"
                    total_match = re.search(total_pattern, itinerary, re.IGNORECASE)

                    if total_match:
                        total_cost = float(total_match.group(1).replace(',', ''))
                    else:
                        # Calculate total
                        total_cost = sum(item["amount"] for item in budget_items)

            # If we have budget items, create and return the breakdown
            if budget_items:
                # Handle special case if total doesn't match sum of items
                items_total = sum(item["amount"] for item in budget_items)
                if abs(items_total - total_cost) > 1.0:  # Allow for minor rounding differences
                    logger.warning(f"Total cost (${total_cost}) doesn't match sum of items (${items_total})")
                    # Trust the explicit total if available, otherwise use the sum
                    if total_cost == 0:
                        total_cost = items_total

                # Ensure all items have descriptions - add generic ones if missing
                for item in budget_items:
                    if not item["description"]:
                        category_lower = item["category"].lower()
                        # Try to match with our descriptions again using partial matching
                        for key, desc in descriptions.items():
                            if key.split()[0] in category_lower:  # Match first word
                                item["description"] = desc
                                break

                        # If still no description, add a generic one
                        if not item["description"]:
                            item["description"] = f"Estimated costs for {item['category']}."

                budget_breakdown = {
                    "currency": currency,
                    "total": total_cost,
                    "items": budget_items
                }

                logger.info(f"Successfully extracted budget breakdown with {len(budget_items)} items")
                return budget_breakdown
            else:
                logger.warning("Found budget section but couldn't extract items")
                return None

        except Exception as e:
            logger.error(f"Error extracting budget breakdown: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

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