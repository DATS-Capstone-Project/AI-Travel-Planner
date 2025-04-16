import os
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from pydantic import BaseModel
from config.settings import SERP_API_KEY

logger = logging.getLogger(__name__)


class EventImage(BaseModel):
    url: str
    alt: Optional[str] = None


class EventLocation(BaseModel):
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class EventPrice(BaseModel):
    amount: float
    currency: str = "USD"


class EventDetails(BaseModel):
    id: str
    title: str
    description: str
    date: str
    time: Optional[str] = None
    location: EventLocation
    images: List[EventImage]
    url: Optional[str] = None
    price: Optional[EventPrice] = None
    category: Optional[str] = None
    venue: Optional[Dict[str, Any]] = None
    ticket_info: Optional[List[Dict[str, Any]]] = None
    event_location_map: Optional[Dict[str, Any]] = None


class EventService:
    """Service for fetching events data using SerpAPI"""

    def __init__(self):
        # API key should be stored in environment variables
        self.api_key = SERP_API_KEY
        self.base_url = "https://serpapi.com/search"

    async def get_events(self, destination: str) -> List[EventDetails]:
        """
        Fetch events for a destination using SerpAPI

        Args:
            destination: The destination to fetch events for

        Returns:
            List of EventDetails
        """
        logger.info(f"Fetching events for {destination}")

        params = {
            "engine": "google_events",
            "q": f"Events in {destination}",
            "hl": "en",
            "gl": "us",
            "api_key": self.api_key
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()

                data = response.json()

                if "events_results" not in data:
                    logger.warning(f"No events found for {destination}")
                    return []

                events_results = data["events_results"]
                return self._parse_events(events_results, destination)

        except Exception as e:
            logger.error(f"Error fetching events for {destination}: {e}")
            # Return mock data as fallback in case of errors
            return self._get_mock_events(destination)

    def _parse_events(self, events_results: List[Dict[str, Any]], destination: str) -> List[EventDetails]:
        """Parse SerpAPI events results into EventDetails objects"""
        events = []

        for i, event in enumerate(events_results):
            try:
                # Extract event data
                title = event.get("title", "Unnamed Event")
                description = event.get("description", "No description available.")

                # Date/time information
                date_info = event.get("date", {})
                date = date_info.get("start_date", "")
                time = date_info.get("when", "")

                # Location data
                venue_name = event.get("venue", {}).get("name", "")
                address = "\n".join(event.get("address", [])) if event.get("address") else ""

                # Split city and country from address if possible
                city = destination.split(',')[0] if ',' in destination else destination


                # Image data
                image_url = ""
                # Try to get the best quality image available
                if event.get("image"):
                    # Full image is preferred
                    image_url = event.get("image")
                elif event.get("thumbnail"):
                    # Fallback to thumbnail
                    image_url = event.get("thumbnail")

                # Add image quality parameters if it's an Unsplash image
                if image_url and "unsplash.com" in image_url and "?" not in image_url:
                    image_url = f"{image_url}?auto=format&fit=crop&w=1200&q=80"

                images = [EventImage(url=image_url, alt=title)] if image_url else []

                # Link data
                event_url = event.get("link", "")

                # Venue data with rating and reviews
                venue_data = event.get("venue", {})
                venue = None
                if venue_data:
                    venue = {
                        "name": venue_data.get("name", ""),
                        "rating": venue_data.get("rating"),
                        "reviews": venue_data.get("reviews"),
                        "link": venue_data.get("link", "")
                    }

                # Event location map
                event_location_map = event.get("event_location_map", {})

                # Ticket information
                ticket_info = []
                if "ticket_info" in event:
                    for ticket in event["ticket_info"]:
                        ticket_info.append({
                            "source": ticket.get("source", ""),
                            "link": ticket.get("link", ""),
                            "link_type": ticket.get("link_type", "more info")
                        })

                # Category/price data
                category = None
                if "type" in event:
                    category = event["type"]

                # Create event object
                event_details = EventDetails(
                    id=f"event_{i + 1}",
                    title=title,
                    description=description,
                    date=date,
                    time=time,
                    location=EventLocation(
                        name=venue_name,
                        address=address,
                        city=city
                    ),
                    images=images if images else [EventImage(
                        url="https://images.unsplash.com/photo-1540575467063-178a50c2df87?auto=format&fit=crop&w=1200&q=80",
                        alt="Event")],
                    url=event_url,
                    category=category,
                    venue=venue,
                    ticket_info=ticket_info,
                    event_location_map=event_location_map
                )

                events.append(event_details)

            except Exception as e:
                logger.error(f"Error parsing event: {e}")
                continue

        return events

    def _get_mock_events(self, destination: str) -> List[EventDetails]:
        """Generate mock events as fallback"""
        # Generate mock events based on destination
        cityName = destination.split(',')[0] if ',' in destination else destination

        return [
            EventDetails(
                id="event1",
                title=f"{cityName} Food Festival",
                description=f"Experience the vibrant flavors of {cityName} at this annual food festival. Sample local cuisine, watch cooking demonstrations, and enjoy live music.",
                date="2023-08-15",
                time="10:00 AM - 8:00 PM",
                location=EventLocation(
                    name=f"{cityName} City Park",
                    address="123 Main Street",
                    city=cityName,
                    country="United States"
                ),
                images=[
                    EventImage(
                        url="https://images.unsplash.com/photo-1555939594-58d7cb561ad1",
                        alt="Food Festival"
                    )
                ],
                price=EventPrice(
                    amount=25,
                    currency="USD"
                ),
                category="Food"
            ),
            EventDetails(
                id="event2",
                title=f"{cityName} Jazz Concert",
                description=f"A night of smooth jazz and fantastic performances from local and international artists in downtown {cityName}.",
                date="2023-08-22",
                time="7:30 PM",
                location=EventLocation(
                    name=f"{cityName} Concert Hall",
                    address="456 Broadway",
                    city=cityName,
                    country="United States"
                ),
                images=[
                    EventImage(
                        url="https://images.unsplash.com/photo-1511192336575-5a79af67a629",
                        alt="Jazz Concert"
                    )
                ],
                price=EventPrice(
                    amount=45,
                    currency="USD"
                ),
                category="Music"
            ),
            EventDetails(
                id="event3",
                title=f"{cityName} Art Exhibition",
                description=f"Explore contemporary art from {cityName}'s most talented artists. This exhibition showcases paintings, sculptures, and digital installations.",
                date="2023-08-10",
                time="9:00 AM - 6:00 PM",
                location=EventLocation(
                    name=f"{cityName} Modern Art Museum",
                    address="789 Gallery Way",
                    city=cityName,
                    country="United States"
                ),
                images=[
                    EventImage(
                        url="https://images.unsplash.com/photo-1531058020387-3be344556be6",
                        alt="Art Exhibition"
                    )
                ],
                price=EventPrice(
                    amount=15,
                    currency="USD"
                ),
                category="Art"
            ),
            EventDetails(
                id="event4",
                title=f"{cityName} Marathon",
                description=f"Join thousands of runners in the annual {cityName} Marathon. The route will take you through the city's most scenic spots.",
                date="2023-09-15",
                time="7:00 AM",
                location=EventLocation(
                    name=f"{cityName} Downtown",
                    address="Start: City Hall Plaza",
                    city=cityName,
                    country="United States"
                ),
                images=[
                    EventImage(
                        url="https://images.unsplash.com/photo-1530137073521-28cda9e30ed5",
                        alt="Marathon"
                    )
                ],
                price=EventPrice(
                    amount=75,
                    currency="USD"
                ),
                category="Sports"
            ),
            EventDetails(
                id="event5",
                title=f"{cityName} Tech Conference",
                description=f"The biggest tech event in {cityName}. Learn about the latest technologies, network with industry professionals, and attend workshops.",
                date="2023-09-22",
                time="9:00 AM - 5:00 PM",
                location=EventLocation(
                    name=f"{cityName} Convention Center",
                    address="101 Tech Boulevard",
                    city=cityName,
                    country="United States"
                ),
                images=[
                    EventImage(
                        url="https://images.unsplash.com/photo-1540575467063-178a50c2df87",
                        alt="Tech Conference"
                    )
                ],
                price=EventPrice(
                    amount=199,
                    currency="USD"
                ),
                category="Technology"
            )
        ]