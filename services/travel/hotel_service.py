from dotenv import load_dotenv
from serpapi import GoogleSearch
from langchain_openai import ChatOpenAI
from datetime import datetime
from typing import Dict, Any
import logging
import os
import json
from config.settings import SERP_API_KEY, OPENAI_API_KEY

load_dotenv()

ENHANCED_HOTEL_ADVISOR_PROMPT_SERPAPI = """
You are an experienced travel advisor specializing in hotel recommendations. Your goal is to help travelers find their perfect accommodation by providing detailed, personalized insights. Be friendly and conversational while maintaining professionalism.

### REQUIRED SECTIONS (Follow this exact order):

1. GREETING & DESTINATION OVERVIEW
- Warm welcome acknowledging the trip dates and destination
- Brief insights about why hotel location matters in this destination
- Any seasonal considerations for the selected dates

2. AVAILABLE HOTEL OPTIONS
[Only include categories that have hotels. For each category (Budget-Friendly/Mid-Range/Luxury), provide:]

Category Name:

**Hotel Name**
- **Rating:** [Rating with review count]
- **Price per Night:** [Price with currency symbol]
- **Total Price:** [Total price with currency symbol]
- **Location:** [Location and neighborhood insights]
- **Property Overview:** [Describe style, atmosphere, notable features]
- **Key Amenities:** [List of amenities]
- **Perfect For:** [Ideal guest types]
- **Nearby Attractions:** [List of nearby attractions]
- **Insider Tip:** [One unique or lesser-known tip]
```

[After EACH category, provide a COMPARATIVE ANALYSIS:]
- Price-to-value comparison between hotels
- Location advantages/disadvantages
- Amenity differences
- Best suited traveler types

3. NEIGHBORHOOD INSIGHTS
[For each neighborhood where hotels are located:]
- Area character and atmosphere
- Safety considerations
- Transportation access
- Dining and entertainment options
- Proximity to major attractions

4. TRAVELER-TYPE RECOMMENDATIONS
[Only include traveler types that have suitable options:]
- Business travelers
- Families
- Luxury seekers
- Budget travelers
- First-time visitors

5. BEST MATCH RECOMMENDATION
**Top Recommendation: [Hotel Name]**
- Why this hotel stands out
- Value for money analysis
- Location benefits
- Key amenities that make it special
- Target traveler match
- Guest satisfaction highlights

[Must include 2-3 sentences explaining why this specific hotel is the best choice]

6. CLOSING
- Summary of key points
- Next steps for booking
- Invitation for questions

### CRITICAL REQUIREMENTS:
- Stay dates: **{checkin} to {checkout}**
- Only show categories with available hotels
- Provide comparative analysis for each category
- Include specific reasoning for the best match
- Base all recommendations on the provided data only

### Hotel Data:
{hotels_data}

{context}
"""

class HotelService:
    def __init__(self):
        self.serpapi_key = SERP_API_KEY
        if not self.serpapi_key:
            raise ValueError("SERPAPI_KEY environment variable is not set")
        
    async def calculate_hotel_budget(self, total_budget: float, num_days: int) -> Dict[str, float]:
        """Calculate hotel budget ranges based on total trip budget"""
        try:
            # Rough breakdown of total budget
            # 40% for hotels, 30% for flights, 30% for food, activities, etc.
            hotel_total_budget = total_budget * 0.4
            per_night_budget = hotel_total_budget / num_days

            # Calculate price ranges
            return {
                "budget_max": per_night_budget * 0.7,  # 70% of average for budget category
                "midrange_max": per_night_budget * 1.2,  # 120% of average for mid-range
                "luxury_min": per_night_budget * 1.2  # Anything above mid-range is luxury
            }
        except Exception as e:
            logging.error(f"Error calculating hotel budget: {str(e)}")
            raise

    async def determine_hotel_category(self, per_night_budget: float) -> str:
        """
        Determine hotel category based on per night budget
        Budget: < $150
        Mid-range: $150-$300
        Luxury: > $300
        """
        if per_night_budget < 150:
            return "budget"
        elif per_night_budget <= 300:
            return "midrange"
        else:
            return "luxury"

    async def get_hotel_results_from_serpapi(self, destination, checkin_date, checkout_date, adults, total_budget, currency="USD", country="us", lang="en"):
        try:
            logging.info(f"Fetching hotels for {destination} from {checkin_date} to {checkout_date} for {adults} adults")
            
            if not isinstance(adults, int) or adults < 1:
                raise ValueError(f"Invalid number of adults: {adults}. Must be a positive integer.")

            # Calculate number of days
            start_date = datetime.strptime(checkin_date, "%Y-%m-%d")
            end_date = datetime.strptime(checkout_date, "%Y-%m-%d")
            num_days = (end_date - start_date).days

            # Calculate hotel budget (40% of total)
            hotel_budget = total_budget * 0.4
            per_night_budget = hotel_budget / num_days

            # Determine category based on per night budget
            category = await self.determine_hotel_category(per_night_budget)
            logging.info(f"Based on per night budget of ${per_night_budget:.2f}, searching for {category} hotels")

            # Base parameters for API call
            params = {
                "engine": "google_hotels",
                "q": f"{destination}",
                "check_in_date": checkin_date,
                "check_out_date": checkout_date,
                "adults": str(adults),
                "children": "0",
                "currency": currency,
                "gl": country,
                "hl": lang,
                "sort_by": "3",  # Sort by lowest price
                "api_key": self.serpapi_key
            }

            # Add category-specific parameters
            if category == "budget":
                params.update({
                    "max_price": str(int(150)),  # Max $150 per night
                    "sort_by": "3"  # Prioritize lowest price
                })
            elif category == "midrange":
                params.update({
                    "min_price": str(int(150)),
                    "max_price": str(int(300)),
                    "rating": "7"  # At least 3.5+ rating
                })
            else:  # luxury
                params.update({
                    "min_price": str(int(300)),
                    "max_price": str(int(per_night_budget)),  # Stay within budget
                    "rating": "8",  # At least 4.0+ rating
                    "hotel_class": "4,5"  # 4-5 star hotels
                })

            # Make API call
            logging.info(f"Searching for {category} hotels with parameters: {params}")
            search = GoogleSearch(params)
            results = search.get_dict()

            if "error" in results:
                error_message = results.get("error", "Unknown error")
                logging.error(f"SerpAPI error: {error_message}")
                raise Exception(f"SerpAPI returned an error: {error_message}")
            
            if "properties" not in results:
                logging.warning(f"No properties found in results. Available keys: {list(results.keys())}")
                return None
                
            properties = results["properties"]
            if not properties:
                logging.warning("Properties array is empty")
                return None
                
            # Transform properties data to match expected hotel format
            hotels = []
            for prop in properties:
                # Price extraction logic remains the same
                rate_per_night = prop.get("rate_per_night", {})
                price_per_night = rate_per_night.get("lowest", "") or rate_per_night.get("before_taxes_fees", "")
                
                total_rate = prop.get("total_rate", {})
                total_price = total_rate.get("lowest", "") or total_rate.get("before_taxes_fees", "")
                
                if not price_per_night and prop.get("prices"):
                    first_price = prop["prices"][0]
                    rate_info = first_price.get("rate_per_night", {})
                    price_per_night = rate_info.get("lowest", "") or rate_info.get("before_taxes_fees", "")
                
                hotel = {
                    "name": prop.get("name", ""),
                    "rating": prop.get("overall_rating", 0),
                    "reviews": prop.get("reviews", 0),
                    "price_per_night": price_per_night or "Price not available",
                    "total_price": total_price or "Total price not available",
                    "location": {
                        "address": prop.get("address", ""),
                        "coordinates": prop.get("gps_coordinates", {})
                    },
                    "description": prop.get("description", ""),
                    "amenities": prop.get("amenities", []),
                    "hotel_class": prop.get("hotel_class", ""),
                    "check_in_time": prop.get("check_in_time", ""),
                    "check_out_time": prop.get("check_out_time", ""),
                    "deal": prop.get("deal", ""),
                    "deal_description": prop.get("deal_description", ""),
                    "location_rating": prop.get("location_rating", 0),
                    "reviews_breakdown": prop.get("reviews_breakdown", []),
                    "nearby_places": prop.get("nearby_places", []),
                    "category": category  # Add the determined category
                }
                hotels.append(hotel)
            
            # Sort hotels by price
            hotels.sort(key=lambda x: float(str(x["price_per_night"]).replace("$", "").replace(",", "")) 
                       if isinstance(x["price_per_night"], (str, int, float)) and 
                       str(x["price_per_night"]).replace("$", "").replace(",", "").replace(".", "").isdigit() 
                       else float('inf'))
            
            logging.info(f"Successfully found {len(hotels)} {category} hotels")
            logging.info("Sample of hotels being sent to LLM advisor:")
            for idx, hotel in enumerate(hotels[:3]):
                logging.info(f"\nHotel {idx + 1}:")
                logging.info(f"Name: {hotel['name']}")
                logging.info(f"Rating: {hotel['rating']} ({hotel['reviews']} reviews)")
                logging.info(f"Price per night: {hotel['price_per_night']}")
                logging.info(f"Total price: {hotel['total_price']}")
                logging.info(f"Hotel class: {hotel['hotel_class']}")
            
            return hotels

        except Exception as e:
            logging.error(f"Error in get_hotel_results_from_serpapi: {str(e)}")
            raise Exception(f"Failed to fetch hotel data from SerpAPI: {str(e)}")

    async def get_best_hotels(self, extracted_details: Dict[str, Any]) -> str:
        try:
            destination = extracted_details.get("destination")
            start_date = extracted_details.get("start_date")
            end_date = extracted_details.get("end_date")
            travelers = extracted_details.get("travelers")
            total_budget = extracted_details.get("budget")

            if not all([destination, start_date, end_date, travelers, total_budget]):
                raise ValueError("Missing required parameters: destination, start_date, end_date, travelers, or budget")

            if not isinstance(travelers, int) or travelers < 1:
                raise ValueError(f"Invalid number of travelers: {travelers}. Must be a positive integer.")

            if not isinstance(total_budget, (int, float)) or total_budget <= 0:
                raise ValueError(f"Invalid budget: {total_budget}. Must be a positive number.")

            # Format dates
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
            
            formatted_start_date = start_date_obj.strftime("%Y-%m-%d")
            formatted_end_date = end_date_obj.strftime("%Y-%m-%d")

            logging.info(f"Searching hotels in {destination} from {formatted_start_date} to {formatted_end_date}")

            hotel_data = await self.get_hotel_results_from_serpapi(
                destination=destination,
                checkin_date=formatted_start_date,
                checkout_date=formatted_end_date,
                adults=travelers,
                total_budget=total_budget
            )

            if not hotel_data:
                return f"Sorry, I couldn't find any hotels in {destination} for your dates and budget. Please try different dates or adjust your budget."

            return await self.get_hotel_recommendations(
                hotels_data=hotel_data,
                checkin=start_date_obj.strftime("%B %d, %Y"),
                checkout=end_date_obj.strftime("%B %d, %Y")
            )

        except ValueError as ve:
            logging.error(f"Validation error: {str(ve)}")
            raise
        except Exception as e:
            logging.error(f"Error in get_best_hotels: {str(e)}")
            raise Exception(f"❌ Failed to fetch hotel data from SerpAPI: {str(e)}")

    async def get_hotels(self, destination: str, start_date: str, end_date: str, travelers: int, budget: float) -> str:
        """Wrapper method for get_best_hotels"""
        extracted_details = {
            "destination": destination,
            "start_date": start_date,
            "end_date": end_date,
            "travelers": travelers,
            "budget": budget
        }
        return await self.get_best_hotels(extracted_details)

    async def get_hotel_recommendations(self, hotels_data, checkin="", checkout="", context=None):
        """Generate hotel recommendations using the LLM"""
        try:
            if not hotels_data:
                return "No hotel data available to generate recommendations."

            context_str = f"\n### Additional Context:\n{context}" if context else ""
            
            prompt = ENHANCED_HOTEL_ADVISOR_PROMPT_SERPAPI.format(
                hotels_data=json.dumps(hotels_data, indent=2),
                checkin=checkin,
                checkout=checkout,
                context=context_str
            )

            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5, openai_api_key=OPENAI_API_KEY)
            messages = [{"role": "user", "content": prompt}]
            logging.info("Generating hotel recommendations...")
            response = await llm.agenerate(messages=[messages])
            return response.generations[0][0].text.strip()

        except Exception as e:
            logging.error(f"Error generating hotel recommendations: {str(e)}")
            raise Exception(f"Failed to generate hotel recommendations: {str(e)}")
