import asyncio
import logging
from typing import TypedDict, Dict, Any, List
from datetime import datetime

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from services.travel.flight_service import FlightService
from services.travel.hotel_service import HotelService
from services.travel.activity_service import ActivityService
from models.trip_details import TripDetails
from config.settings import OPENAI_API_KEY, CONVERSATION_MODEL




# Configure logger
logger = logging.getLogger(__name__)


# Define our state structure
class TravelState(TypedDict):
    session_id: str
    trip_details: Dict[str, Any]
    flights: List[Dict[str, Any]]
    hotels: List[Dict[str, Any]]
    activities: List[Dict[str, Any]]
    itinerary: str


class TravelSupervisor:
    """Supervisor agent that coordinates travel planning workflow"""

    def __init__(
            self,
            flight_service: FlightService,
            hotel_service: HotelService,
            activity_service: ActivityService,
            model_name: str = CONVERSATION_MODEL
    ):
        """
        Initialize the travel supervisor agent

        Args:
            flight_service: Service for flight operations
            hotel_service: Service for hotel operations
            activity_service: Service for activity operations
            model_name: LLM model to use for coordination
        """
        self.flight_service = flight_service
        self.hotel_service = hotel_service
        self.activity_service = activity_service
        self.model = ChatOpenAI(api_key=OPENAI_API_KEY, model="gpt-4.1-mini", temperature=0)
        #self.distance_service = DistanceService()
        self.logger = logging.getLogger(__name__)

        # Build the workflow graph
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """Build the workflow graph for travel planning"""
        # Create the graph with our state
        workflow = StateGraph(TravelState)

        # Add nodes
        workflow.add_node("start", self._supervisor_start)
        workflow.add_node("parallel_booking", self._run_parallel_agents)
        # Should add a node here before crating the itinerary to check the budget and if the user wants to change it if the min(budget) > the budget of the user
        workflow.add_node("create_itinerary", self._create_itinerary)
        workflow.add_node("finish", self._supervisor_finish)

        # Add edges
        workflow.add_edge("start", "parallel_booking")
        workflow.add_edge("parallel_booking", "create_itinerary")
        workflow.add_edge("create_itinerary", "finish")
        workflow.add_edge("finish", END)

        # Set entry point
        workflow.set_entry_point("start")

        # Compile the workflow
        return workflow.compile()

    def _supervisor_start(self, state: TravelState) -> Dict[str, Any]:
        """Initial node that starts the parallel booking process"""
        logger.info(f"Starting travel planning for session {state['session_id']}")

        # Always proceed to parallel booking
        return {"agent": "parallel_booking"}

    async def _flights_agent(self, state: TravelState) -> Dict[str, Any]:
        """Agent that handles flight booking"""
        logger.info(f"✈️ Flights agent started at: {datetime.now().strftime('%H:%M:%S')}")
        start_time = datetime.now()

        trip_details = state["trip_details"]

        # Extract necessary fields
        origin = trip_details.get("origin")
        destination = trip_details.get("destination")
        start_date = trip_details.get("start_date")
        end_date = trip_details.get("end_date")
        travelers = trip_details.get("travelers")

        try:
            # Call flight service
            flights = await self.flight_service.get_flights(
    origin=origin,
    destination=destination,
    start_date=start_date,
    end_date=end_date,
    travelers=travelers
)

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            logger.info(f"✈️ Flights agent finished at: {end_time.strftime('%H:%M:%S')} (took {execution_time:.2f}s)")

            return {"flights": flights}
        except Exception as e:
            logger.error(f"Error in flights agent: {e}")
            return {"flights": [{"error": str(e)}]}

    async def _hotels_agent(self, state: TravelState) -> Dict[str, Any]:
        """Agent that handles hotel booking"""
        logger.info(f"🏨 Hotels agent started at: {datetime.now().strftime('%H:%M:%S')}")
        start_time = datetime.now()

        trip_details = state["trip_details"]

        # Extract necessary fields
        destination = trip_details.get("destination")
        start_date = trip_details.get("start_date")
        end_date = trip_details.get("end_date")
        budget = trip_details.get("budget")

        try:
            # Call hotel service
            hotels = await self.hotel_service.get_hotels(
                destination=destination,
                start_date=start_date,
                end_date=end_date,
                travelers=trip_details.get("travelers", 1),
                budget=budget
            )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            logger.info(f"🏨 Hotels agent finished at: {end_time.strftime('%H:%M:%S')} (took {execution_time:.2f}s)")

            return {"hotels": hotels}
        except Exception as e:
            logger.error(f"Error in hotels agent: {e}")
            return {"hotels": [{"error": str(e)}]}

    async def _activities_agent(self, state: TravelState) -> Dict[str, Any]:
        """Agent that handles activity recommendations"""
        logger.info(f"🎭 Activities agent started at: {datetime.now().strftime('%H:%M:%S')}")
        start_time = datetime.now()

        trip_details = state["trip_details"]

        # Extract necessary fields
        destination = trip_details.get("destination")
        preferences = trip_details.get("activity_preferences", "")

        try:
            # Call activities service
            activities = await self.activity_service.get_activities(
                destination=destination,
                preferences=preferences
            )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            logger.info(f"🎭 Activities agent finished at: {end_time.strftime('%H:%M:%S')} (took {execution_time:.2f}s)")

            return {"activities": activities}
        except Exception as e:
            logger.error(f"Error in activities agent: {e}")
            return {"activities": [{"error": str(e)}]}

    async def _run_parallel_agents(self, state: TravelState) -> Dict[str, Any]:
        # Run all agents in parallel
        flights_task = asyncio.create_task(self._flights_agent(state))
        hotels_task = asyncio.create_task(self._hotels_agent(state))
        activities_task = asyncio.create_task(self._activities_agent(state))

        flights_result, hotels_result, activities_result = await asyncio.gather(
            flights_task,
            hotels_task, activities_task
        )

        hotels_content = hotels_result.get("hotels", "")
        activities_content = activities_result.get("activities", "")

        # Update state
        state.update({
            "flights": flights_result.get("flights", []),
            "hotels": hotels_content,
            "activities": activities_content
            #"proximity_check": proximity_message
        })

        return state



    async def _create_itinerary(self, state: TravelState) -> Dict[str, Any]:
        """Create a comprehensive itinerary from all collected data"""
        trip_details = state["trip_details"]
        flights = state["flights"]
        # Use selected hotel from trip details if available, otherwise use hotels from parallel search
        hotels = trip_details.get("selected_hotel", state["hotels"])
        activities = state["activities"]

        print("Trip details:", trip_details)
        print("Flights:", flights)
        print("Hotels:", hotels)
        print("Activities:", activities)

        # Use LLM to create a well-formatted itinerary
        messages = [
            HumanMessage(content=f"""
                You are an experienced travel consultant creating a personalized travel plan. Write in a friendly, conversational tone as if you're directly advising the traveler.

IMPORTANT: The following data contains pre-formatted information from specialized travel services. Maintain the detailed information while creating a cohesive travel plan.

Based on the following information, create a detailed travel plan:

TRIP DETAILS:
{trip_details}

FLIGHT OPTIONS:
{flights}

HOTEL OPTIONS:
{hotels}

ACTIVITIES INFORMATION:
{activities}

FORMATTING INSTRUCTIONS:
- Use proper markdown formatting with headers (##, ###) for each section
- Include blank lines between paragraphs and sections (use double line breaks)
- Use bullet points (- ) for lists
- Ensure there are no unnecessary line breaks within paragraphs
- Use proper indentation for readability
- For tables, use markdown table format with proper spacing
- Preserve exact formatting of flight details, hotel names, prices, and other key information

GUIDANCE FOR CREATING THE TRAVEL PLAN:

1. START WITH A PERSONALIZED GREETING:
   - Begin with a warm, personalized welcome that acknowledges their specific trip details
   - Express enthusiasm about their trip to {trip_details.get("destination")}
   - If they've provided preferences, explicitly acknowledge them (e.g., "I've noticed you're interested in [preferences]")
   - Briefly highlight what makes the destination special during their travel dates

2. INCLUDE A DEDICATED TRAVELER PREFERENCES SECTION (if preferences exist):
   - Right after the introduction, create a special section titled "YOUR PREFERENCES"
   - Directly address each preference mentioned in the trip details
   - Provide detailed information about each preference, including:
     * Specific locations related to the preference
     * How to best experience it during their trip
     * Any special considerations (timing, tickets, reservations needed)
     * For preferences outside the main destination, include transportation options and travel time
   - Make this section visually distinctive and prominent
   - End the section with a transition to the rest of the plan

3. PRESENT FLIGHT RECOMMENDATIONS:
   - Preserve the detailed flight information exactly as provided
   - Present the best flight options for both outbound and return journey
   - Highlight key benefits of each recommended flight (timing, amenities, price)
   - If flights are organized by time of day, maintain this structure
   - Ensure each flight option is clearly separated with blank lines

4. PRESENT HOTEL RECOMMENDATIONS:
   - Maintain all hotel details as provided (name, rating, price, location, amenities)
   - Explain why certain hotels might be better suited for their trip
   - If preferences exist, highlight hotels that are conveniently located near their interests
   - Include practical details about hotel locations and proximity to attractions
   - Add blank lines between different hotel options for clarity
   
5. PRESENT ACTIVITIES RECOMMENDATIONS:
   - Summarize the activities in a friendly, engaging manner
   - Highlight unique experiences and attractions in the destination
   - If preferences exist, prioritize activities that match their interests
   - Include specific details about each activity (location, timing, cost)
   - Use bullet points for easy reading and clear separation of different activities
   - Add blank lines between different activity options
   - Use the provided activity data to ensure accuracy and detail

6. CREATE A DAY-BY-DAY ITINERARY:
   - Provide a daily activity plan that incorporates both attractions and dining
   - If preferences exist, ensure these are prominently featured in the itinerary on appropriate days
   - For each day, include:
        Morning:
            - Activities with times
            - Transportation details
            - Meal suggestions
            
        Afternoon:
            - Activities with times
            - Transportation details
            - Meal suggestions
            
        Evening:
            - Activities with times
            - Transportation details
            - Meal suggestions
            
        Daily Tips:
            - Weather considerations
            - What to bring
            - Local customs
            - Money-saving tips
            - Use the activities data to create a balanced itinerary
   - For the food recommendations, use the specific restaurants and details from the activities data
   - For the attractions, use the specific places and details from the activities data
   - Balance busy days with more relaxed ones
   - Use clear headings for each day (### Day 1 - Thursday, April 10)
   - Ensure any preference-related activities are highlighted or marked in some way
   - Add blank lines between different sections of each day

7. INCLUDE A COMPLETE BUDGET BREAKDOWN:
   - Itemize all expected costs: flights, accommodation, activities, food, local transportation
   - Don't multiply the costs by the number of travelers for flights
   - Display the flight costs as is and don't calculate for the round trip
   - If preferences require special expenses (e.g., day trips), include these as separate line items
   - Provide a total estimated cost and compare it to their stated budget of {trip_details.get("budget", "N/A")}
   - Offer money-saving tips that are specific to the destination
   - Use a clear tabular format for the budget items where appropriate

8. CLOSE WITH PRACTICAL TRAVEL TIPS:
   - Weather expectations for their specific travel dates
   - Local transportation recommendations
   - Packing suggestions tailored to their activities and preferences
   - Any special considerations for the season or local events
   - For any preferences requiring special planning (like excursions), add specific tips
   - Add a warm closing message with well wishes for their trip

Your response should feel like a personalized conversation with a knowledgeable friend who's excited about their trip. Include specific details from all data sources while maintaining a cohesive, easy-to-follow travel plan with proper spacing and formatting.

CRITICAL: If "Preferences" is present in the trip details, ensure these preferences are prominently addressed throughout the plan, especially in the dedicated preferences section and daily itinerary.
            """)
        ]

        response = await self.model.ainvoke(messages)
        itinerary = response.content

        return {"itinerary": itinerary}

    def _supervisor_finish(self, state: TravelState) -> Dict[str, Any]:
        """Final node that completes the workflow"""
        logger.info(f"Travel planning completed for session {state['session_id']}")

        logger.info(f"flight information: {state['flights']}")
        logger.info(f"hotel information: {state['hotels']}")
        logger.info(f"activities information: {state['activities']}")
        logger.info(f"itinerary information: {state['itinerary']}")


        # Return the final state
        return {
            "itinerary": state["itinerary"],
            "flights": state["flights"],
            "hotels": state["hotels"],
            "activities": state["activities"]
        }


    async def plan_trip(self, session_id: str, trip_details: TripDetails) -> Dict[str, Any]:
        """
        Plan a trip using the workflow

        Args:
            session_id: Session identifier
            trip_details: Trip details object

        Returns:
            Dictionary with planning results
        """
        # Initialize the state
        initial_state = {
            "session_id": session_id,
            "trip_details": trip_details.to_dict(),
            "flights": [],
            "hotels": [],
            "activities": [],
            "itinerary": ""
        }

        # Run the workflow
        result = await self.workflow.ainvoke(initial_state)

        return result
