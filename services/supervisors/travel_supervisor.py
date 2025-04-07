
import asyncio
import logging
from typing import TypedDict, Dict, Any, List
from datetime import datetime

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from services.travel.flight import FlightService
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
        self.model = ChatOpenAI(api_key=OPENAI_API_KEY, model="gpt-4o-mini", temperature=0)
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

        # Default proximity message
        # proximity_message = "Could not determine hotel/activity proximity."
        #
        # try:
        #     hotels_list = hotels_content.split("|")
        #     activities_list = activities_content.split("|")
        #
        #     # Call DistanceService
        #     proximity_human_msg = self.distance_service.check_proximity(hotels_list, activities_list)
        #
        #     proximity_message = proximity_human_msg.content
        #
        #     if "Recommend searching for closer hotels" in proximity_message:
        #         # Refine hotels
        #         refined_hotels_msg = self.hotel_service.get_hotels(
        #             destination=f"{state['trip_details']['destination']} city center",
        #             start_date=state["trip_details"]["start_date"],
        #             end_date=state["trip_details"]["end_date"],
        #             budget=state["trip_details"].get("budget")
        #         )
        #         hotels_content = refined_hotels_msg.content
        #         proximity_message += "\nRefined hotel search applied."
        #
        # except Exception as e:
        #     self.logger.error(f"Proximity check failed: {e}")
        #     proximity_message = f"Proximity check error: {e}"

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
        hotels = state["hotels"]
        activities = state["activities"]

        print("Trip details:", trip_details)
        print("Flights:", flights)
        print("Hotels:", hotels)
        print("Activities:", activities)

        # Use LLM to create a well-formatted itinerary
        messages = [
            HumanMessage(content=f"""
                You are an experienced travel consultant creating a personalized travel plan. Write in a friendly, conversational tone as if you're directly advising the traveler.

                Based on the following information, create a detailed travel plan:

                TRIP DETAILS:
                {trip_details}

                FLIGHT OPTIONS:
                {flights}

                HOTEL OPTIONS:
                {hotels}
                 Present hotels exactly as provided, maintaining all details and formatting. Only show available categories (Budget-Friendly/Mid-Range/Luxury).

            For each hotel:
            ```
            **[Hotel Name]**
            - Rating and reviews
            - Price per night and total price
            - Location details
            - Property description
            - Key amenities
            - Perfect for (target travelers)
            - Nearby attractions
            - Special tips
            ```

            After each category, provide a COMPARATIVE ANALYSIS of:
            - Price-to-value comparison
            - Location advantages/disadvantages
            - Amenity differences
            - Best suited traveler types
         
             BUDGET BREAKDOWN
            Provide a detailed budget breakdown:
            - Flights
            - Accommodation
            - Activities
            - Meals and incidentals
            - Transportation
            - Total estimated cost
            
            
            FINAL RECOMMENDATIONS
            Provide a "BEST MATCH" recommendation including:
            - Best flight option with reasoning
            - Best hotel option with reasoning
            - Must-do activities
            - Money-saving tips
            - Practical travel tips


                RECOMMENDED ACTIVITIES:
                {activities}

                IMPORTANT INSTRUCTIONS:

                1. Begin with a warm, personalized greeting acknowledging their specific trip

                2. For the Flight Options section:
                   - MAINTAIN THE EXACT FLIGHT INFORMATION FORMAT from the input
                   - Keep all flight details intact (airline, departure/arrival times, duration, price, stops)
                   - DO NOT summarize or modify the flight information
                   - DO NOT use labels like "Flight A", "Flight B", etc.
                   - Preserve the grouping by time of day (Morning/Afternoon/Evening)
                   - When recommending flights, refer to them by their actual details (e.g., "the IndiGo flight at 11:25 AM")

                3. For the Hotel Options section:
                   - MAINTAIN THE EXACT HOTEL INFORMATION FORMAT from the input
                   - Keep all hotel details intact (name, rating, price, location, amenities)
                   - DO NOT summarize or modify the hotel information
                   - DO NOT use generic labels like "Hotel A", "Hotel B", etc.
                   - Organize hotels logically by price category (Budget-Friendly, Mid-Range, Luxury)
                   - When recommending hotels, refer to them by their actual names and details (e.g., "the Hyatt Centric at $111 with beach access")
                   - If hotel details provided are NULL or INSUFFICIENT, present options with your best knowledge, including FULL DETAILS for hotel name, price range, location, amenities, and target travelers

                4. For the Activities section:
                   - Present recommended activities with full details as provided
                   - Organize logically by day or category
                   - Make specific suggestions that complement the selected hotels and overall trip experience
                   - For each activity, include approximate time requirements and any practical tips

                5. Include a Budget Breakdown section showing estimated total costs for:
                   - Flights
                   - Accommodation
                   - Activities
                   - Meals and incidentals
                   - Transportation

                6. End with a friendly closing that offers continued assistance

                ESSENTIAL: Both the flight and hotel sections MUST maintain the identical format as provided in the input, with all details preserved exactly as given.
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
