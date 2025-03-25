def hotel_scrape_task(url):
    return f"""Follow these steps in order:
    Go to {url}
    1. Enter the location in the location field where "Search for places, hotels, and more"
   
    2. Extract the list of hotels displayed on the search results page.
   
    3. For each hotel, collect the following details:
        - Hotel name
        - Rating (out of 5)
        - Number of reviews
        - Price per night
        - Amenities (pool, free Wi-Fi, breakfast, etc.)
        - Location
        - Direct Google Hotels link to the hotel result (not generic brand site)
        - Check in Date
        - Check out Date
        
        

    4. Create a structured JSON response with hotel listings:
        {{
            "hotels": [
                {{
                    "name": "...",
                    "rating": "...",
                    "num_reviews": "...",
                    "price_per_night": "...",
                    "amenities": ["...", "..."],
                    "location": "...",
                    "booking_links": ["..."],
                    "check-in date": ["..."],
                    "check-out date": ["..."],
                    
                    
                }},
                ...
            ]
        }}

    5. Important:
        - Ensure the extracted data is accurate and complete.
        - Use a structured format with clear keys.
        - Prioritize hotels with high ratings and competitive prices.
    """
