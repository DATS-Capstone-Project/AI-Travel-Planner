import asyncio
import json
import logging
from typing import Dict, Any, List

from openai import OpenAI
from config.settings import OPENAI_API_KEY, ASSISTANT_NAME, CONVERSATION_MODEL
from repositories.session_repository import SessionRepository
from services.extraction.extractor_factory import ExtractorFactory
from services.travel.activity_service import ActivityService
from services.travel.flight_service import FlightService
from services.travel.hotel_service import HotelService
from services.supervisors.travel_supervisor import TravelSupervisor

# Configure logger
logger = logging.getLogger(__name__)


class AssistantsManager:
    """Manager for OpenAI Assistants API interactions"""

    def __init__(
            self,
            session_repository: SessionRepository,
            flight_service: FlightService,
            hotel_service: HotelService,
            activity_service: ActivityService,
            extractor_type: str = "llm"
    ):
        """
        Initialize the assistants manager

        Args:
            session_repository: Repository for session data
            flight_service: Service for flight operations
            hotel_service: Service for hotel operations
            activity_service: Service for activity operations
            extractor_type: Type of entity extractor to use
        """
        self.client = OpenAI(api_key=OPENAI_API_KEY, default_headers={"OpenAI-Beta": "assistants=v2"})
        self.session_repository = session_repository
        self.flight_service = flight_service
        self.hotel_service = hotel_service
        self.activity_service = activity_service
        self.extractor = ExtractorFactory.create_extractor(extractor_type)
        self.assistant_id = self._create_or_get_assistant()
        # Initialize the supervisor
        self.travel_supervisor = TravelSupervisor(
            flight_service=flight_service,
            hotel_service=hotel_service,
            activity_service=activity_service
        )

    def _create_or_get_assistant(self) -> str:
        """Create or retrieve the travel planning assistant"""
        try:
            # List assistants to check if travel planner exists
            logger.info(f"Checking for existing {ASSISTANT_NAME} assistant")
            assistants = self.client.beta.assistants.list(limit=100)

            for assistant in assistants.data:
                if assistant.name == ASSISTANT_NAME:
                    logger.info(f"Found existing {ASSISTANT_NAME} assistant: {assistant.id}")
                    return assistant.id

            # Create a new assistant if not found
            logger.info(f"Creating new {ASSISTANT_NAME} assistant")
            assistant = self.client.beta.assistants.create(
                name=ASSISTANT_NAME,
                instructions="""
                    You are a helpful travel planning assistant. 
                    Help users plan trips by gathering information about:
                    - origin (REQUIRED): Provide the departure city from where you are starting your journey.
                    - destination (REQUIRED)
                    - start date (REQUIRED): accept any date format the user provides
                    - end date (REQUIRED): accept any date format the user provides
                    - number of travelers (REQUIRED): pay attention if user already mentioned this
                    - budget (OPTIONAL but important): This is the TOTAL budget for the entire trip, not per night
                    - activity preferences (OPTIONAL but important): What the user wants to do at the destination

                    IMPORTANT WORKFLOW:
                    1. COLLECTION PHASE: First, collect ALL required information and try to collect optional information
                    2. CONFIRMATION PHASE: Once you have all required information, ask the user to confirm
                    3. PLANNING PHASE: When the user confirms, let them know you're now working on their travel plan

                    GUIDELINES:
                    1. Accept dates in any natural format users provide (like "March 2nd", "next week", etc.)
                    2. Only suggest travel dates within the next 6 months as our systems can't book further ahead
                    3. If a user says "I'm with X people" or similar, count the total correctly (user + X people)
                    4. Don't ask for information the user has already provided
                    5. Ask where the user is starting its journey from. Ask for origin city.
                    6. Never proceed to confirmation until you have all required fields.
                    7. Always try to collect optional fields before confirmation for a better experience.
                    8. When the system tells you what fields are missing, focus on collecting those specific fields.

                    When confirming details, format the confirmation as a clear summary of all the collected information
                    about their trip (both required and optional), and explicitly ask if they want to proceed with planning.

                    Only after receiving explicit confirmation AND having all required fields should you use handoff to the supervisor agent to
                    generate an itinerary.
                    
                    After the user confirms all trip details, do not validate dates or call any tools. Immediately proceed to planning the itinerary with the supervisor agent
                    """,

                model=CONVERSATION_MODEL,
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "validate_dates",
                            "description": "Validate that end date is after start date",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "start_date": {
                                        "type": "string",
                                        "description": "Start date in YYYY-MM-DD format"
                                    },
                                    "end_date": {
                                        "type": "string",
                                        "description": "End date in YYYY-MM-DD format"
                                    }
                                },
                                "required": ["start_date", "end_date"]
                            }
                        }
                    }
                ]
            )
            logger.info(f"Created new {ASSISTANT_NAME} assistant: {assistant.id}")
            return assistant.id

        except Exception as e:
            logger.error(f"Failed to create or get assistant: {e}")
            raise Exception(f"Failed to create or get assistant: {e}")

    def _get_thread(self, session_id: str) -> str:
        """Get or create a thread for the session"""
        thread_id = self.session_repository.get_thread_id(session_id)

        if not thread_id:
            thread = self.client.beta.threads.create()
            thread_id = thread.id
            self.session_repository.set_thread_id(session_id, thread_id)
            logger.info(f"Created new thread {thread_id} for session {session_id}")

        return thread_id

    def _check_confirmation(self, message: str) -> bool:
        """Check if the message contains a confirmation"""
        confirmation_keywords = [
            "yes", "yeah", "yep", "sure", "ok", "okay", "proceed",
            "confirm", "book", "go ahead", "sounds good"
        ]

        message_lower = message.lower()

        # Check for negative responses that include confirmation keywords
        negation_before_confirmation = any(
            neg + " " + conf in message_lower
            for neg in ["don't", "do not", "cannot", "can't", "not"]
            for conf in confirmation_keywords
        )

        if negation_before_confirmation:
            return False

        # Check for positive confirmation
        has_confirmation = any(keyword in message_lower.split() for keyword in confirmation_keywords)

        # Look for negation
        has_negation = any(word in message_lower.split() for word in ["no", "nope", "don't", "not", "cancel"])

        return has_confirmation and not has_negation

    def _create_missing_fields_message(self, missing_required: List[str], missing_optional: List[str]) -> str:
        """Create a message about missing fields for the assistant"""
        context_msg = "System note: The following information is still needed from the user:\n"

        if missing_required:
            context_msg += "\nRequired fields (must collect BEFORE confirmation):\n"
            for field in missing_required:
                context_msg += f"- {field}\n"

        if missing_optional:
            context_msg += "\nOptional fields (should try to collect BEFORE confirmation):\n"
            for field in missing_optional:
                context_msg += f"- {field}\n"

        context_msg += "\nPlease ask the user about these specific fields in a natural, conversational way."
        return context_msg

    async def process_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """
        Process a user message using the Assistants API

        Args:
            session_id: Session identifier
            message: User message text

        Returns:
            Dictionary with response text and extracted data
        """
        thread_id = self._get_thread(session_id)
        logger.info(f"Processing message for session {session_id}, thread {thread_id}")
        logger.info(f"User message: {message}")

        # Get existing trip details for context
        existing_trip_details = self.session_repository.get_trip_details(session_id)

        # Extract entities from message with context from existing details
        extracted_details = self.extractor.extract(message, existing_details=existing_trip_details)
        logger.info(f"Extracted details: {extracted_details.to_dict()}")
        if not extracted_details.origin:
            logger.warning("Origin is missing from extracted details. Please ask the user for the departure city.")

        # Update session data with extracted details
        self.session_repository.update_trip_details(session_id, extracted_details.to_dict())

        # Get updated trip details after extraction
        trip_details = self.session_repository.get_trip_details(session_id)
        trip_dict = trip_details.to_dict()

        # Check for date errors in the trip details and prompt the user to correct them if found.
        if trip_dict.get("start_date")=="Error" or trip_dict.get("end_date")=="Error":

            return {
                "response": "Please ensure your start date is in the future and within the next 6 months, and that your end date is later than your start date and also within the next 6 months. Also, check if your end date is after your start date.",
                "extracted_data": trip_dict
            }

        # Check what information is still missing
        missing_required = trip_details.missing_required_fields()
        missing_optional = trip_details.missing_optional_fields()

        # Only set confirmation if all required fields are present and user has confirmed
        if self._check_confirmation(message) and trip_details.is_ready_for_confirmation():
            logger.info(f"Detected confirmation in user message and all required fields present")
            self.session_repository.set_confirmed(session_id, True)

            # HANDOFF TO SUPERVISOR AGENT after confirmation
            if self.session_repository.is_confirmed(session_id):
                logger.info(f"Handing off to supervisor agent for session {session_id}")

                # Add a message to the thread informing the user about handoff
                self.client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content="System note: User confirmed trip details. Handing off to planning supervisor."
                )

                # Call supervisor agent
                try:
                    # Call the supervisor agent with the trip details
                    supervisor_result = await self.travel_supervisor.plan_trip(
                        session_id=session_id,
                        trip_details=trip_details
                    )

                    logger.info(f"Supervisor agent completed planning: {supervisor_result}")

                    # Return the supervisor's response
                    return {
                        "response": supervisor_result.get("itinerary",
                                                          "I've created your travel plan based on your preferences."),
                        "extracted_data": trip_details.to_dict()
                    }
                except Exception as e:
                    logger.error(f"Error in supervisor agent: {e}")
                    return {
                        "response": "I'm sorry, but I encountered an error while planning your trip. Please try again.",
                        "extracted_data": trip_details.to_dict()
                    }
        elif self._check_confirmation(message) and not trip_details.is_ready_for_confirmation():
            logger.warning(f"User attempted to confirm but missing required fields: {missing_required}")
            # Do not set confirmation if required fields are missing

        # Add context as a system message with trip details and missing fields
        if trip_details and any(value is not None for value in trip_details.__dict__.values()):
            context_msg = "System note: I've detected the following trip information:\n"
            for key, value in trip_details.__dict__.items():
                if value is not None:
                    context_msg += f"- {key}: {value}\n"

            # Append missing fields information if any
            if missing_required or missing_optional:
                context_msg += "\n" + self._create_missing_fields_message(missing_required, missing_optional)
            else:
                context_msg += "\nAll required and optional fields have been collected. You can now confirm details with the user."
            context_msg += "\n\nPlease use this information and avoid asking for details that have already been provided."

            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=context_msg
            )
            logger.info("Added context message with detected trip details and missing fields")

        # Add the user's original message to the thread
        self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message
        )

        # Run the assistant on the thread
        run = self.client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=self.assistant_id
        )

        logger.info(f"Started run {run.id} for thread {thread_id}")

        # Poll for the run to complete
        while run.status in ["queued", "in_progress", "requires_action"]:
            # Short sleep to avoid hammering the API
            await asyncio.sleep(0.5)

            run = self.client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )

            logger.debug(f"Run status: {run.status}")

            # Handle tool calls if needed - we only have validate_dates now
            if run.status == "requires_action":
                logger.info(f"Run requires action")
                tool_outputs = []

                for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                    function_name = tool_call.function.name
                    arguments_str = tool_call.function.arguments
                    arguments = json.loads(arguments_str)

                    # We only handle validate_dates now
                    if function_name == "validate_dates":
                        start_date = arguments.get("start_date")
                        end_date = arguments.get("end_date")

                        from datetime import datetime
                        try:
                            start = datetime.strptime(start_date, "%Y-%m-%d")
                            end = datetime.strptime(end_date, "%Y-%m-%d")
                            result = str(end > start)
                        except Exception as e:
                            logger.error(f"Date validation error: {e}")
                            result = "False"

                        tool_outputs.append({
                            "tool_call_id": tool_call.id,
                            "output": result
                        })

                # Submit tool outputs
                logger.info(f"Submitting tool outputs")
                run = self.client.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread_id,
                    run_id=run.id,
                    tool_outputs=tool_outputs
                )

        if run.status == "failed":
            logger.error(f"Run failed: {run.last_error}")
            return {
                "response": "I'm sorry, but I encountered an error processing your request. Please try again.",
                "extracted_data": trip_details.to_dict()
            }

        # Retrieve the latest message from the assistant
        logger.info(f"Run completed with status: {run.status}")
        messages = self.client.beta.threads.messages.list(
            thread_id=thread_id
        )

        # Return the latest assistant message
        for message in messages.data:
            if message.role == "assistant":
                if hasattr(message.content[0], 'text'):
                    response = message.content[0].text.value
                    logger.info(f"Assistant response: {response}")
                    return {
                        "response": response,
                        "extracted_data": trip_details.to_dict()
                    }

        logger.error("No assistant message found")
        return {
            "response": "I'm having trouble processing your request. Please try again.",
            "extracted_data": trip_details.to_dict()
        }
