# import asyncio
# import json
# import logging
# from typing import Dict, Any, List
#
# from openai import OpenAI
# from config.settings import OPENAI_API_KEY, ASSISTANT_NAME, CONVERSATION_MODEL
# from repositories.session_repository import SessionRepository
# from services.extraction.extractor_factory import ExtractorFactory
# from services.travel.activity_service import ActivityService
# from services.travel.flight_service import FlightService
# from services.travel.hotel_service import HotelService
# from services.supervisors.travel_supervisor import TravelSupervisor
#
# # Configure logger
# logger = logging.getLogger(__name__)
#
#
# class AssistantsManager:
#     """Manager for OpenAI Assistants API interactions (no tools)"""
#
#     def __init__(
#             self,
#             session_repository: SessionRepository,
#             flight_service: FlightService,
#             hotel_service: HotelService,
#             activity_service: ActivityService,
#             extractor_type: str = "llm"
#     ):
#         """
#         Initialize the assistants manager without any tool usage.
#         """
#         # Using the new v2 Assistants API
#         self.client = OpenAI(api_key=OPENAI_API_KEY, default_headers={"OpenAI-Beta": "assistants=v2"})
#
#         self.session_repository = session_repository
#         self.flight_service = flight_service
#         self.hotel_service = hotel_service
#         self.activity_service = activity_service
#         self.extractor = ExtractorFactory.create_extractor(extractor_type)
#         self.assistant_id = self._create_or_get_assistant()
#
#         # Initialize the supervisor
#         self.travel_supervisor = TravelSupervisor(
#             flight_service=flight_service,
#             hotel_service=hotel_service,
#             activity_service=activity_service
#         )
#
#     def _create_or_get_assistant(self) -> str:
#         """Create or retrieve the travel planning assistant (no tools)."""
#         try:
#             # List existing assistants
#             logger.info(f"Checking for existing {ASSISTANT_NAME} assistant")
#             assistants = self.client.beta.assistants.list(limit=100)
#
#             for assistant in assistants.data:
#                 if assistant.name == ASSISTANT_NAME:
#                     logger.info(f"Found existing {ASSISTANT_NAME} assistant: {assistant.id}")
#                     return assistant.id
#
#             # Create a new assistant if not found
#             logger.info(f"Creating new {ASSISTANT_NAME} assistant (no tools)")
#             assistant = self.client.beta.assistants.create(
#                 name=ASSISTANT_NAME,
#                 instructions="""
#                     You are a helpful travel planning assistant.
#                     Help users plan trips by gathering information about:
#                     - origin (REQUIRED)
#                     - destination (REQUIRED)
#                     - start date (REQUIRED)
#                     - end date (REQUIRED)
#                     - number of travelers (REQUIRED)
#                     - budget (OPTIONAL)
#                     - activity preferences (OPTIONAL)
#
#                     IMPORTANT WORKFLOW:
#                     1. COLLECTION PHASE:
#                        - Review the system notes carefully to see what information you already have
#                        - DO NOT ask for information that has already been provided
#                        - Focus on collecting missing REQUIRED fields first
#                        - Then try to collect OPTIONAL fields if the user is responsive
#
#                     2. CONFIRMATION PHASE:
#                        - Once all required fields are collected, summarize the trip details
#                        - Ask the user to confirm if everything is correct
#
#                     3. PLANNING PHASE:
#                        - After user confirms, hand off to the supervisor agent
#                        - Do not call any tools, just proceed with planning
#
#                     CRITICAL: Always check the system notes at the start of each message to avoid
#                     asking for information you already have. This creates a much better user experience.
#                 """,
#                 model=CONVERSATION_MODEL,
#                 # No 'tools' argument here
#             )
#             logger.info(f"Created new {ASSISTANT_NAME} assistant: {assistant.id}")
#             return assistant.id
#
#         except Exception as e:
#             logger.error(f"Failed to create or get assistant: {e}")
#             raise Exception(f"Failed to create or get assistant: {e}")
#
#     def _get_thread(self, session_id: str) -> str:
#         """Get or create a thread for the session."""
#         thread_id = self.session_repository.get_thread_id(session_id)
#         if not thread_id:
#             thread = self.client.beta.threads.create()
#             thread_id = thread.id
#             self.session_repository.set_thread_id(session_id, thread_id)
#             logger.info(f"Created new thread {thread_id} for session {session_id}")
#         return thread_id
#
#     def _check_confirmation(self, message: str) -> bool:
#         """Check if the message contains a confirmation."""
#         confirmation_keywords = [
#             "yes", "yeah", "yep", "sure", "ok", "okay", "proceed",
#             "confirm", "book", "go ahead", "sounds good", "please"
#         ]
#
#         message_lower = message.lower().strip()
#
#         # Log the message being checked for confirmation
#         logger.info(f"Checking message for confirmation: '{message_lower}'")
#
#         # Special case for common phrases
#         if message_lower in ["yes", "yes please", "yes, please", "sure", "ok", "okay", "proceed", "go ahead"]:
#             logger.info(f"Direct match found for confirmation: '{message_lower}'")
#             return True
#
#         # Check for negative responses that include confirmation keywords
#         negation_before_confirmation = any(
#             neg + " " + conf in message_lower
#             for neg in ["don't", "do not", "cannot", "can't", "not"]
#             for conf in confirmation_keywords
#         )
#         if negation_before_confirmation:
#             logger.info(f"Negation before confirmation detected: '{message_lower}'")
#             return False
#
#         # Check for positive confirmation
#         has_confirmation = any(keyword in message_lower.split() for keyword in confirmation_keywords)
#         logger.info(f"Has confirmation keyword: {has_confirmation}")
#
#         # Look for negation
#         has_negation = any(word in message_lower.split() for word in ["no", "nope", "don't", "not", "cancel"])
#         logger.info(f"Has negation: {has_negation}")
#
#         result = has_confirmation and not has_negation
#         logger.info(f"Confirmation result for '{message_lower}': {result}")
#         return result
#
#     def _create_missing_fields_message(self, missing_required: List[str], missing_optional: List[str]) -> str:
#         """Create a message about missing fields for the assistant."""
#         context_msg = "System note: The following information is still needed from the user:\n"
#
#         if missing_required:
#             context_msg += "\nRequired fields (must collect BEFORE confirmation):\n"
#             for field in missing_required:
#                 context_msg += f"- {field}\n"
#
#         if missing_optional:
#             context_msg += "\nOptional fields (should try to collect BEFORE confirmation):\n"
#             for field in missing_optional:
#                 context_msg += f"- {field}\n"
#
#         context_msg += "\nPlease ask the user about these specific fields in a natural, conversational way."
#         return context_msg
#
#     async def process_message(self, session_id: str, message: str) -> Dict[str, Any]:
#         """
#         Process a user message using the Assistants API, with no tool usage.
#         """
#         thread_id = self._get_thread(session_id)
#         logger.info(f"Processing message for session {session_id}, thread {thread_id}")
#         logger.info(f"User message: {message}")
#
#         # Check for any active runs and wait for them to complete
#         active_runs = self.client.beta.threads.runs.list(thread_id=thread_id)
#
#         if active_runs.data:
#             logger.info(f"Found {len(active_runs.data)} run(s) for thread {thread_id}, checking status")
#             for run in active_runs.data:
#                 if run.status in ["queued", "in_progress", "requires_action"]:
#                     logger.info(f"Found active run {run.id} with status {run.status}, waiting for completion")
#                     while True:
#                         run_status = self.client.beta.threads.runs.retrieve(
#                             thread_id=thread_id,
#                             run_id=run.id
#                         )
#                         if run_status.status in ["completed", "failed", "cancelled", "expired"]:
#                             break
#                         await asyncio.sleep(1)  # Wait 1 second before checking again
#
#         # Pull existing trip details for context
#         existing_trip_details = self.session_repository.get_trip_details(session_id)
#
#         # Extract entities (no tool calls, just your custom extractor)
#         extracted_details = self.extractor.extract(message, existing_details=existing_trip_details)
#         logger.info(f"Extracted details: {extracted_details.to_dict()}")
#
#         # Warn if origin is still missing
#         if not extracted_details.origin:
#             logger.warning("Origin is missing from extracted details. Please ask the user for the departure city.")
#
#         # Update session data with extracted details
#         self.session_repository.update_trip_details(session_id, extracted_details.to_dict())
#
#         # Check final trip details
#         trip_details = self.session_repository.get_trip_details(session_id)
#         trip_dict = trip_details.to_dict()
#
#         # If you have date validations in your business logic, handle them here
#         if trip_dict.get("start_date") == "Error" or trip_dict.get("end_date") == "Error":
#             return {
#                 "response": "Please ensure your start date and end date are valid and within the next 6 months.",
#                 "extracted_data": trip_dict
#             }
#
#         # Determine missing fields
#         missing_required = trip_details.missing_required_fields()
#         missing_optional = trip_details.missing_optional_fields()
#
#         # Check for user confirmation + whether we have all required fields
#         logger.info(f"Trip details ready for confirmation: {trip_details.is_ready_for_confirmation()}")
#         logger.info(f"Missing required fields: {missing_required}")
#         logger.info(f"Missing optional fields: {missing_optional}")
#
#         if self._check_confirmation(message) and trip_details.is_ready_for_confirmation():
#             logger.info("User confirmed with all required fields present.")
#             self.session_repository.set_confirmed(session_id, True)
#             is_confirmed = self.session_repository.is_confirmed(session_id)
#             logger.info(f"Session confirmation status after update: {is_confirmed}")
#
#             # Handoff to supervisor agent
#             if is_confirmed:
#                 logger.info(f"Handing off to supervisor agent for session {session_id}")
#                 try:
#                     self.client.beta.threads.messages.create(
#                         thread_id=thread_id,
#                         role="user",
#                         content="System note: User confirmed trip details. Handing off to planning supervisor."
#                     )
#                     logger.info("Added handoff message to thread")
#
#                     logger.info("Calling travel supervisor plan_trip method")
#                     logger.info(f"Trip details being sent to supervisor: {trip_details.to_dict()}")
#                     supervisor_result = await self.travel_supervisor.plan_trip(
#                         session_id=session_id,
#                         trip_details=trip_details
#                     )
#                     logger.info(f"Supervisor agent completed planning: {supervisor_result}")
#                     return {
#                         "response": supervisor_result.get("itinerary",
#                                                           "I've created your travel plan based on your preferences."),
#                         "extracted_data": trip_details.to_dict()
#                     }
#                 except Exception as e:
#                     logger.error(f"Error in supervisor agent: {e}")
#                     import traceback
#                     logger.error(f"Traceback: {traceback.format_exc()}")
#                     return {
#                         "response": "I'm sorry, but I encountered an error while planning your trip. Please try again.",
#                         "extracted_data": trip_details.to_dict()
#                     }
#
#         elif self._check_confirmation(message) and not trip_details.is_ready_for_confirmation():
#             logger.warning(f"User tried to confirm but missing required fields: {missing_required}")
#             # Don't set confirmation; continue collecting data
#
#         # Create a system note about what's missing (if anything)
#         if trip_details and any(value is not None for value in trip_details.__dict__.values()):
#             context_msg = "System note: Current trip information:\n"
#             for key, value in trip_details.__dict__.items():
#                 if value is not None and key != 'confidence_levels':
#                     context_msg += f"✓ {key}: {value}\n"
#
#             if missing_required or missing_optional:
#                 context_msg += "\nMISSING INFORMATION:"
#                 if missing_required:
#                     context_msg += "\nRequired (must collect):\n"
#                     for field in missing_required:
#                         context_msg += f"⚠️ {field}\n"
#                 if missing_optional:
#                     context_msg += "\nOptional (should try to collect):\n"
#                     for field in missing_optional:
#                         context_msg += f"○ {field}\n"
#                 context_msg += "\nPlease focus on collecting the missing required information first."
#             else:
#                 context_msg += "\n✓ All required and optional fields have been collected. You can now confirm the details with the user."
#
#             context_msg += "\n\nIMPORTANT: Use this information to avoid asking for details that have already been provided. Focus on collecting missing required fields."
#
#             self.client.beta.threads.messages.create(
#                 thread_id=thread_id,
#                 role="user",
#                 content=context_msg
#             )
#             logger.info("Added context message with detected trip details and missing fields")
#
#         # Add the user's message to the thread
#         self.client.beta.threads.messages.create(
#             thread_id=thread_id,
#             role="user",
#             content=message
#         )
#
#         # Run the assistant on the thread (no tools)
#         run = self.client.beta.threads.runs.create(
#             thread_id=thread_id,
#             assistant_id=self.assistant_id
#         )
#         logger.info(f"Started run {run.id} for thread {thread_id}")
#
#         # Wait for the run to complete
#         while True:
#             run_status = self.client.beta.threads.runs.retrieve(
#                 thread_id=thread_id,
#                 run_id=run.id
#             )
#             if run_status.status in ["completed", "failed", "cancelled", "expired"]:
#                 break
#             await asyncio.sleep(1)  # Wait 1 second before checking again
#
#         # Get the assistant's response
#         messages = self.client.beta.threads.messages.list(
#             thread_id=thread_id,
#             order="desc",
#             limit=1
#         )
#
#         assistant_message = next(
#             (msg for msg in messages.data if msg.role == "assistant"),
#             None
#         )
#
#         if assistant_message:
#             logger.info(f"Latest assistant response: {assistant_message.content[0].text.value}")
#             return {
#                 "response": assistant_message.content[0].text.value,
#                 "extracted_data": trip_details.to_dict()
#             }
#         else:
#             logger.warning("No assistant message found")
#             return {
#                 "response": "I'm having trouble processing that. Could you please try again?",
#                 "extracted_data": trip_details.to_dict()
#             }