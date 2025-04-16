import os
import json
import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from functools import lru_cache
import time
from config.settings import GOOGLE_PLACES_API_KEY

logger = logging.getLogger(__name__)


# Models for Google Places API responses
class PlaceLocation(BaseModel):
    lat: float
    lng: float


class Geometry(BaseModel):
    location: PlaceLocation


class Photo(BaseModel):
    photo_reference: str
    height: int
    width: int
    html_attributions: List[str] = []


class OpeningHours(BaseModel):
    open_now: Optional[bool] = None
    periods: Optional[List[Dict[str, Any]]] = None
    weekday_text: Optional[List[str]] = None


class PlaceResult(BaseModel):
    place_id: str
    name: str
    types: List[str] = []
    vicinity: Optional[str] = None
    formatted_address: Optional[str] = None
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    price_level: Optional[int] = None
    photos: Optional[List[Photo]] = None
    geometry: Geometry
    opening_hours: Optional[OpeningHours] = None
    icon: Optional[str] = None
    icon_background_color: Optional[str] = None
    icon_mask_base_uri: Optional[str] = None
    business_status: Optional[str] = None


class PlacesResponse(BaseModel):
    results: List[PlaceResult] = []
    status: str
    next_page_token: Optional[str] = None


class PlaceDetailsResponse(BaseModel):
    result: Optional[PlaceResult] = None
    status: str


class DayTripDestination(BaseModel):
    name: str
    place_id: str
    distance_text: str
    distance_value: int  # in meters
    duration_text: str
    duration_value: int  # in seconds
    photo_reference: Optional[str] = None
    top_attractions: List[PlaceResult] = []
    location: PlaceLocation


class EnrichedPlace(BaseModel):
    place_id: str
    name: str
    types: List[str] = []
    geometry: Geometry
    photos: List[Photo] = []
    description: str
    rating: float
    user_ratings_total: int
    formatted_address: str
    international_phone_number: str
    website: str
    url: str


class GooglePlacesService:
    """Service for interacting with Google Places API"""

    def __init__(self):
        # API key should be stored in environment variables
        self.api_key = GOOGLE_PLACES_API_KEY
        if not self.api_key:
            logger.warning("GOOGLE_PLACES_API_KEY not found in environment variables")

        self.places_base_url = "https://maps.googleapis.com/maps/api/place"
        self.distance_matrix_url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        self.photo_base_url = f"{self.places_base_url}/photo"
        self.cache_expiry = 3600  # Cache results for 1 hour
        self.place_types = {
            "attractions": ["tourist_attraction", "amusement_park", "aquarium", "art_gallery", "museum"],
            "museums": ["museum"],
            "landmarks": ["tourist_attraction", "church", "landmark", "monument"],
            "restaurants": ["restaurant", "food"],
            "parks": ["park", "campground", "natural_feature"],
            "nightlife": ["night_club", "bar", "casino"],
            "family-friendly": ["amusement_park", "aquarium", "zoo", "movie_theater", "park"],
            "hiking": ["park", "natural_feature", "campground", "point_of_interest", "establishment", "hike_trails", "trekking"]
        }
        self.cache = {}

    async def _fetch_next_page(self, page_token: str) -> List[PlaceResult]:
        """
        Fetch the next page of results using a page token
        """
        url = f"{self.places_base_url}/nearbysearch/json"
        params = {
            "pagetoken": page_token,
            "key": self.api_key
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                if data["status"] != "OK":
                    return []

                places_response = PlacesResponse(**data)
                return places_response.results

        except Exception as e:
            logger.error(f"Error fetching next page: {e}")
            return []

    async def place_details(self, place_id: str) -> Optional[PlaceResult]:
        """
        Get detailed information about a specific place

        Args:
            place_id: The Google Place ID

        Returns:
            Detailed information about the place
        """
        cache_key = f"details_{place_id}"

        # Check cache
        if cache_key in self.cache:
            cache_data, timestamp = self.cache[cache_key]
            if datetime.now() - timestamp < timedelta(seconds=self.cache_expiry):
                return cache_data

        params = {
            "place_id": place_id,
            "fields": "name,place_id,formatted_address,geometry,icon,photos,price_level,rating,types,user_ratings_total,opening_hours,vicinity",
            "key": self.api_key
        }

        try:
            url = f"{self.places_base_url}/details/json"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                if data["status"] != "OK":
                    logger.error(f"Error in Google Places Details API: {data['status']}")
                    return None

                details_response = PlaceDetailsResponse(**data)
                result = details_response.result

                # Save to cache
                self.cache[cache_key] = (result, datetime.now())

                return result

        except Exception as e:
            logger.error(f"Error getting place details: {e}")
            return None

    def get_photo_url(self, photo_reference: str, max_width: int = 400) -> str:
        """
        Get the URL for a place photo

        Args:
            photo_reference: The photo reference from the Places API
            max_width: Maximum width of the photo

        Returns:
            URL for the photo
        """
        if not photo_reference or not isinstance(photo_reference, str) or photo_reference.strip() == "":
            logger.warning("Empty or invalid photo reference provided")
            return ""

        # Trim any whitespace
        photo_reference = photo_reference.strip()

        # Handle any potential URL formatting issues
        if photo_reference.startswith("http"):
            # If it's already a URL, return it directly
            logger.debug(f"Photo reference is already a URL: {photo_reference}")
            return photo_reference

        # Construct the Google Photos API URL
        url = f"{self.photo_base_url}?photoreference={photo_reference}&maxwidth={max_width}&key={self.api_key}"
        logger.debug(f"Generated photo URL: {url}")
        return url

    async def _geocode_location(self, location: str) -> Optional[Dict[str, float]]:
        """
        Convert a location name to coordinates using Google's Geocoding API

        Args:
            location: The location name (e.g., "Seattle", "New York", etc.)

        Returns:
            Dictionary with lat and lng or None if geocoding failed
        """
        # Check if the input is already coordinates (lat,lng)
        if "," in location and all(
                part.replace('.', '').replace('-', '').isdigit()
                for part in location.split(',')
        ):
            parts = location.split(',')
            return {"lat": float(parts[0]), "lng": float(parts[1])}

        # Create a cache key for this location
        cache_key = f"geocode_{location.lower()}"

        # Check cache first
        if cache_key in self.cache:
            cache_data, timestamp = self.cache[cache_key]
            # Geocoding results don't change often, so use a longer cache expiry
            if datetime.now() - timestamp < timedelta(days=30):
                logger.info(f"Using cached geocode for {location}")
                return cache_data

        # Use Google's Geocoding API
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": location,
            "key": self.api_key
        }

        try:
            logger.info(f"Geocoding location: {location}")
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                if data["status"] == "OK" and data["results"]:
                    # Extract coordinates from the API response
                    coords = data["results"][0]["geometry"]["location"]
                    result = {
                        "lat": coords["lat"],
                        "lng": coords["lng"]
                    }

                    # Save to cache
                    self.cache[cache_key] = (result, datetime.now())

                    logger.info(f"Successfully geocoded {location} to {result}")
                    return result
                else:
                    logger.warning(f"Geocoding error: {data['status']}")
                    if "error_message" in data:
                        logger.warning(f"Error message: {data['error_message']}")
        except Exception as e:
            logger.error(f"Error during geocoding: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

        # Fallback to hardcoded coordinates if API call fails
        # Hardcoded coordinates for common cities as fallback
        common_cities = {
            "los angeles": {"lat": 34.0522, "lng": -118.2437},
            "chicago": {"lat": 41.8781, "lng": -87.6298},
            "san francisco": {"lat": 37.7749, "lng": -122.4194},
            "miami": {"lat": 25.7617, "lng": -80.1918},
            "las vegas": {"lat": 36.1699, "lng": -115.1398},
            "denver": {"lat": 39.7392, "lng": -104.9903},
            "boston": {"lat": 42.3601, "lng": -71.0589},
            "austin": {"lat": 30.2672, "lng": -97.7431},
            "portland": {"lat": 45.5152, "lng": -122.6784},
            "washington dc": {"lat": 38.9072, "lng": -77.0369},
            "washington": {"lat": 38.9072, "lng": -77.0369},
            "dallas": {"lat": 32.7767, "lng": -96.7970},
            "philadelphia": {"lat": 39.9526, "lng": -75.1652},
            "atlanta": {"lat": 33.7490, "lng": -84.3880},
            "paris": {"lat": 48.8566, "lng": 2.3522},
            "london": {"lat": 51.5074, "lng": -0.1278},
            "tokyo": {"lat": 35.6762, "lng": 139.6503},
            "sydney": {"lat": 33.8688, "lng": 151.2093},
            "rome": {"lat": 41.9028, "lng": 12.4964},
            "barcelona": {"lat": 41.3851, "lng": 2.1734},
            "berlin": {"lat": 52.5200, "lng": 13.4050},
            "toronto": {"lat": 43.6532, "lng": -79.3832}
        }

        # Check if we have hardcoded coordinates for this city
        location_lower = location.lower()
        if location_lower in common_cities:
            logger.info(f"Using hardcoded coordinates for {location}")
            return common_cities[location_lower]

        # If we have a state name in the location, try to extract city name
        if "," in location:
            city = location.split(",")[0].strip().lower()
            if city in common_cities:
                logger.info(f"Falling back to hardcoded coordinates for {city}")
                return common_cities[city]

        logger.error(f"Failed to geocode location: {location}")
        return None

    async def _fetch_details_for_places(self, places: List[PlaceResult]) -> List[EnrichedPlace]:
        """Fetch details for multiple places concurrently."""
        results = []

        # Create tasks for all place details fetches
        tasks = []
        for place in places:
            task = asyncio.create_task(self._get_place_details(place))
            tasks.append(task)

        # Wait for all tasks to complete, handling any failures
        for i, task in enumerate(tasks):
            try:
                place_details = await task
                results.append(place_details)
            except Exception as e:
                logger.warning(f"Failed to get details for place {places[i].name}: {str(e)}")
                # Fallback to mock data if we can't get real details
                results.append(self._create_mock_place_details(places[i]))

        return results

    def _create_mock_place_details(self, place: PlaceResult) -> EnrichedPlace:
        """Create mock place details when API fails"""
        logger.info(f"Creating mock details for {place.name}")

        # Generate a deterministic but random-seeming rating between 3.5 and 4.8
        place_id_sum = sum(ord(c) for c in place.place_id if c.isalnum())
        rating = 3.5 + (place_id_sum % 13) / 10  # Between 3.5 and 4.8

        # Generate mock descriptions based on place name
        mock_descriptions = {
            "tacoma": "A vibrant port city with beautiful waterfront views and a thriving arts scene. Visit the Museum of Glass and the Chihuly Bridge of Glass for stunning glass art displays.",
            "bellevue": "An upscale city with excellent shopping at Bellevue Square and beautiful parks. The Bellevue Botanical Garden offers 53 acres of cultivated gardens and natural wetlands.",
            "olympia": "Washington's capital city featuring historic architecture and a picturesque setting on the Puget Sound. Don't miss the Washington State Capitol Campus and Percival Landing.",
            "everett": "A coastal city known for Boeing's aircraft assembly plant and lovely waterfront. Visit the Flying Heritage & Combat Armor Museum for aviation history.",
            "port angeles": "Gateway to Olympic National Park with spectacular mountain and ocean views. Take the ferry to Victoria, BC or explore Hurricane Ridge for amazing hiking.",
            "leavenworth": "A Bavarian-styled village nestled in the Cascade Mountains. Famous for its Oktoberfest celebrations, charming architecture, and outdoor recreation.",

            "philadelphia": "Historic city where the Declaration of Independence was signed. Visit Independence Hall, the Liberty Bell, and enjoy authentic Philly cheesesteaks.",
            "boston": "One of America's oldest cities with rich Revolutionary War history. Walk the Freedom Trail, visit Fenway Park, and explore the renowned Museum of Fine Arts.",
            "atlantic city": "Famous boardwalk city with casinos, entertainment, and beaches. The historic Boardwalk offers shopping, dining, and classic seaside amusements.",
            "new haven": "Home to Yale University with impressive architecture and museums. The Yale University Art Gallery and Peabody Museum of Natural History are must-visits.",
            "hartford": "Connecticut's capital with a rich literary history. Tour the Mark Twain House and visit the Wadsworth Atheneum, America's oldest public art museum.",

            "napa": "World-renowned wine region with hundreds of hillside vineyards. Take a wine tour, enjoy fine dining, or soar above the valley in a hot air balloon.",
            "monterey": "Coastal city famous for its aquarium and Cannery Row. The scenic 17-Mile Drive offers spectacular views of Pebble Beach and the Pacific coastline.",
            "sacramento": "California's capital city with Gold Rush history and modern amenities. The Old Sacramento Historic District features museums and riverfront attractions.",
            "santa cruz": "Beach town known for its iconic boardwalk, surfing culture, and redwood forests. The Santa Cruz Beach Boardwalk is California's oldest surviving amusement park.",
            "sonoma": "Historic wine country town centered around a charming plaza. Visit mission-era buildings, sample wines at local tasting rooms, and enjoy farm-to-table cuisine."
        }

        # Get a normalized name for lookup
        normalized_name = place.name.lower().replace(" ", "")

        # Default description if not in our mock data
        description = mock_descriptions.get(normalized_name,
                                            f"{place.name} is a charming destination with plenty to offer visitors. "
                                            f"Explore local attractions, enjoy the scenery, and experience the unique culture of this area.")

        # Create a basic enriched place with mock data
        return EnrichedPlace(
            place_id=place.place_id,
            name=place.name,
            types=place.types,
            geometry=place.geometry,
            photos=place.photos if hasattr(place, 'photos') else [],
            description=description,
            rating=rating,
            user_ratings_total=int(rating * 100),  # Mock number of ratings
            formatted_address=f"{place.name}, United States",
            international_phone_number="+1 (555) 123-4567",
            website="https://example.com",
            url=f"https://maps.google.com/?q={place.name.replace(' ', '+')}"
        )

    async def _get_place_details(self, place: PlaceResult) -> EnrichedPlace:
        """Fetch detailed information for a place using its place_id"""
        try:
            logger.info(f"Fetching details for place: {place.name}")

            # Create a place_details request
            fields = [
                "name", "place_id", "types", "geometry", "photos",
                "formatted_address", "international_phone_number",
                "rating", "user_ratings_total", "website", "url"
            ]

            # Make the details request
            details_result = self.client.place(
                place_id=place.place_id,
                fields=fields
            )

            # Try to fetch details, if available
            details = details_result.get("result", {})

            if not details:
                logger.warning(f"No details found for {place.name}")
                return self._create_mock_place_details(place)

            # Try to fetch a description via the textual_analysis method
            # This could be replaced with a real API call if available
            description = await self._generate_place_description(place.name, details.get("types", []))

            # Create the enriched place object
            return EnrichedPlace(
                place_id=details.get("place_id", place.place_id),
                name=details.get("name", place.name),
                types=details.get("types", place.types),
                geometry=details.get("geometry", place.geometry),
                photos=details.get("photos", getattr(place, "photos", [])),
                description=description,
                rating=details.get("rating", 4.0),
                user_ratings_total=details.get("user_ratings_total", 100),
                formatted_address=details.get("formatted_address", f"{place.name}, US"),
                international_phone_number=details.get("international_phone_number", "+1 (555) 123-4567"),
                website=details.get("website", "https://example.com"),
                url=details.get("url", f"https://maps.google.com/?q={place.name.replace(' ', '+')}")
            )

        except Exception as e:
            logger.error(f"Error getting place details for {place.name}: {str(e)}")
            raise e

    async def _generate_place_description(self, place_name: str, place_types: List[str]) -> str:
        """Generate a description for a place based on its name and types"""
        # In a real implementation, this could call an LLM API or another service
        # For now, we'll use template-based descriptions

        type_descriptions = {
            "locality": "city",
            "administrative_area_level_1": "state",
            "administrative_area_level_2": "county",
            "country": "country",
            "natural_feature": "natural attraction",
            "point_of_interest": "point of interest",
            "establishment": "establishment",
            "tourist_attraction": "tourist attraction",
            "park": "park",
            "museum": "museum",
            "art_gallery": "art gallery",
            "restaurant": "restaurant",
            "food": "dining venue",
            "cafe": "café"
        }

        # Find the most specific type available
        place_type = "destination"
        for type_name in place_types:
            if type_name in type_descriptions:
                place_type = type_descriptions[type_name]
                break

        # Basic template
        description = f"{place_name} is a popular {place_type} known for its unique character and attractions. "
        description += f"Visitors to {place_name} can enjoy exploring the local culture, scenery, and amenities."

        return description

    async def find_day_trips(self, origin: str, radius_km: int = 150,
                             min_duration_minutes: int = 30,
                             max_duration_minutes: int = 180) -> List[DayTripDestination]:
        """
        Find potential day trip destinations within a certain distance of an origin

        Args:
            origin: The starting location (e.g. "New York")
            radius_km: The maximum distance to search (in km)
            min_duration_minutes: Minimum travel time for a day trip (in minutes)
            max_duration_minutes: Maximum travel time for a day trip (in minutes)

        Returns:
            List of day trip destinations with distance, duration, and attractions
        """
        # Make a unique cache key that includes all parameters
        cache_key = f"daytrips_{origin}_{radius_km}_{min_duration_minutes}_{max_duration_minutes}"

        # Force clear any existing cache for this origin to ensure fresh data
        for key in list(self.cache.keys()):
            if key.startswith(f"daytrips_{origin}_"):
                del self.cache[key]
                logger.info(f"Cleared cache for key: {key}")

        # Always find cities within the radius to get fresh data
        cities = await self._find_cities_near(origin, radius_km)
        if not cities:
            logger.warning(f"No cities found within {radius_km}km of {origin}")
            return []

        # Get distances and travel times
        destinations_str = [f"{city.geometry.location.lat},{city.geometry.location.lng}" for city in cities]

        # Geocode the origin if it's a string
        origin_coords = await self._geocode_location(origin)
        if not origin_coords:
            logger.error(f"Failed to geocode origin: {origin}")
            return []

        origin_str = f"{origin_coords['lat']},{origin_coords['lng']}"

        # Get travel times and distances using Distance Matrix API
        distances = await self._get_distance_matrix(origin_str, destinations_str)
        if not distances:
            logger.warning(f"No distance information available for cities near {origin}")
            return []

        # Filter cities based on travel time
        day_trip_destinations = []
        for i, city in enumerate(cities):
            if i >= len(distances):
                continue

            distance = distances[i]
            if distance is None:
                logger.warning(f"No distance information for {city.name}, skipping")
                continue

            duration_minutes = distance["duration_value"] // 60

            # Filter based on travel time and ensure we're respecting the radius
            if (min_duration_minutes <= duration_minutes <= max_duration_minutes and
                    distance["distance_value"] <= radius_km * 1000):  # Convert km to meters

                # For each potential day trip, find top attractions
                top_attractions = await self.nearby_search(
                    f"{city.geometry.location.lat},{city.geometry.location.lng}",
                    radius=5000,
                    category="attractions"
                )

                # Get a photo for the city
                photo_ref = None
                if city.photos and len(city.photos) > 0:
                    photo_ref = city.photos[0].photo_reference

                day_trip = DayTripDestination(
                    name=city.name,
                    place_id=city.place_id,
                    distance_text=distance["distance_text"],
                    distance_value=distance["distance_value"],
                    duration_text=distance["duration_text"],
                    duration_value=distance["duration_value"],
                    photo_reference=photo_ref,
                    top_attractions=top_attractions[:5],  # Limit to top 5 attractions
                    location=city.geometry.location
                )

                day_trip_destinations.append(day_trip)

        # Log the results for debugging
        logger.info(f"Found {len(day_trip_destinations)} day trip destinations for {origin} within {radius_km}km")

        # Sort destinations by distance (closest first)
        day_trip_destinations.sort(key=lambda x: x.distance_value)

        # Save to cache with current timestamp
        self.cache[cache_key] = (day_trip_destinations, datetime.now())

        return day_trip_destinations

    async def _find_cities_near(self, location: str, radius_km: int) -> List[PlaceResult]:
        """Find cities, towns, or regions near a location for day trip planning"""
        # Log the function call for debugging
        logger.info(f"Finding cities near {location} within {radius_km}km radius using Google Places API")

        # Convert radius from km to meters
        radius_meters = radius_km * 1000

        # First try to find cities - large localities
        cities = await self.nearby_search(
            location,
            radius=radius_meters,
            type_filter="locality"  # Cities and towns
        )
        logger.info(f"Found {len(cities)} localities near {location}")

        # If we have few results, expand to other administrative areas
        if len(cities) < 5:
            logger.info(f"Found fewer than 5 localities, expanding search to administrative areas")
            admin_areas = await self.nearby_search(
                location,
                radius=radius_meters,
                type_filter="administrative_area_level_2"  # Counties/districts
            )
            logger.info(f"Found {len(admin_areas)} administrative areas near {location}")
            cities.extend(admin_areas)

        # If still few results, try points of interest
        if len(cities) < 5:
            logger.info(f"Still fewer than 5 results, expanding to tourist attractions")
            attractions = await self.nearby_search(
                location,
                radius=radius_meters,
                type_filter="tourist_attraction"
            )
            logger.info(f"Found {len(attractions)} tourist attractions near {location}")
            cities.extend(attractions)

        # If still few results, try natural features
        if len(cities) < 5:
            logger.info(f"Still fewer than 5 results, expanding to natural features")
            natural_features = await self.nearby_search(
                location,
                radius=radius_meters,
                type_filter="natural_feature"
            )
            logger.info(f"Found {len(natural_features)} natural features near {location}")
            cities.extend(natural_features)

        # Filter out the origin city itself
        origin_lower = location.lower()
        filtered_cities = [city for city in cities if origin_lower not in city.name.lower()]

        logger.info(f"After filtering out origin, found {len(filtered_cities)} potential day trip destinations")

        # Remove duplicate locations by place_id
        unique_cities = {}
        for city in filtered_cities:
            if city.place_id not in unique_cities:
                unique_cities[city.place_id] = city

        filtered_cities = list(unique_cities.values())
        logger.info(f"After removing duplicates, found {len(filtered_cities)} unique destinations")

        return filtered_cities

    async def nearby_search(self, location: str, radius: int = 5000,
                            type_filter: Optional[str] = None,
                            keyword: Optional[str] = None,
                            category: Optional[str] = None) -> List[PlaceResult]:
        """
        Search for places near a specific location using the Google Places Nearby Search API

        Args:
            location: The location to search near (e.g. "New York" or latitude,longitude)
            radius: Search radius in meters (default 5000 = 5km)
            type_filter: Place type to filter by (e.g. "restaurant", "museum")
            keyword: Additional keyword to filter results
            category: Category from predefined categories (attractions, museums, etc.)

        Returns:
            List of place results
        """
        # Create cache key
        cache_key = f"nearby_{location}_{radius}_{type_filter}_{keyword}_{category}"

        # Force fresh data - don't use cached results
        if cache_key in self.cache:
            del self.cache[cache_key]
            logger.info(f"Cleared cache for key: {cache_key}")

        # Convert location to lat,lng if it's a string place name
        if "," not in location and not location.replace('.', '').replace('-', '').isdigit():
            geocode_result = await self._geocode_location(location)
            if not geocode_result:
                logger.error(f"Failed to geocode location: {location}")
                return []
            location = f"{geocode_result['lat']},{geocode_result['lng']}"

        # Set type filter from category if provided
        if category and category in self.place_types:
            type_filter = self.place_types[category][0]  # Use the first type in the category

        params = {
            "location": location,
            "radius": radius,
            "key": self.api_key
        }

        if type_filter:
            params["type"] = type_filter

        if keyword:
            params["keyword"] = keyword

        try:
            url = f"{self.places_base_url}/nearbysearch/json"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                if data["status"] != "OK" and data["status"] != "ZERO_RESULTS":
                    logger.error(f"Error in Google Places API: {data['status']}")
                    if "error_message" in data:
                        logger.error(f"Error message: {data['error_message']}")
                    return []

                results = []
                if data["status"] == "OK":
                    places_response = PlacesResponse(**data)
                    results = places_response.results

                    # Save to cache
                    self.cache[cache_key] = (results, datetime.now())

                    # Handle pagination if there are more results
                    if "next_page_token" in data and data["next_page_token"]:
                        # Google requires a delay before using next_page_token
                        await asyncio.sleep(2)
                        next_page = await self._fetch_next_page(data["next_page_token"])
                        if next_page:
                            results.extend(next_page)

                return results

        except Exception as e:
            logger.error(f"Error in nearby search: {e}")
            return []

    async def _get_distance_matrix(self, origin: str, destinations: List[str]) -> List[Dict[str, Any]]:
        """
        Get travel time and distance information using the Distance Matrix API

        Args:
            origin: Origin coordinates (lat,lng)
            destinations: List of destination coordinates (lat,lng)

        Returns:
            List of dictionaries with distance and duration information
        """
        if not destinations:
            logger.warning("No destinations provided for distance matrix")
            return []

        # Create a cache key that includes the specific destinations
        cache_key = f"distance_matrix_{origin}_to_{','.join(destinations)}"

        # Force fresh data - don't use cached results
        if cache_key in self.cache:
            del self.cache[cache_key]
            logger.info(f"Cleared cache for key: {cache_key}")

        # Process in batches of 25 (API limit)
        batch_size = 25
        all_results = []

        for i in range(0, len(destinations), batch_size):
            batch = destinations[i:i + batch_size]
            destinations_param = "|".join(batch)

            params = {
                "origins": origin,
                "destinations": destinations_param,
                "mode": "driving",
                "key": self.api_key
            }

            try:
                logger.info(f"Fetching distances from {origin} to {len(batch)} destinations")
                async with httpx.AsyncClient() as client:
                    response = await client.get(self.distance_matrix_url, params=params)
                    response.raise_for_status()
                    data = response.json()

                    if data["status"] != "OK":
                        logger.error(f"Error in Distance Matrix API: {data['status']}")
                        if "error_message" in data:
                            logger.error(f"Error message: {data['error_message']}")
                        continue

                    for row in data["rows"]:
                        for element in row["elements"]:
                            if element["status"] == "OK":
                                result = {
                                    "distance_text": element["distance"]["text"],
                                    "distance_value": element["distance"]["value"],
                                    "duration_text": element["duration"]["text"],
                                    "duration_value": element["duration"]["value"]
                                }
                                all_results.append(result)
                            else:
                                logger.warning(f"Distance matrix element status: {element['status']}")
                                all_results.append(None)

            except Exception as e:
                logger.error(f"Error in distance matrix: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                return []

        logger.info(f"Received distance information for {len(all_results)} destinations")
        return all_results
