def flight_scrape_task(url):
    return f"""Follow these steps in order:
    Go to {url}
    1. Find and click the 'Search' button on the page

    2. For the outbound flight (first leg of the journey):
        - Identify the best 5 outbound flight based on price, number of stops, and duration.
        - Store the outbound flight details including:
            * Departure date & time (local)  
            * Arrival date & time (local)  
            * Origin & destination airports (Airport full names, ex: "Los Angeles International Airport")  
            * Full flight duration (in “Xh Ym” format)  
            * Number of stops (integer)  
            * Layover airports & layover durations  
            * Airline(s) (e.g. “Frontier”)  
            * Individual leg prices (numeric only) if given separately
        - Capture multiple options if available


    4. Return all the information captured in a structured format.

    5. Important:
        - Make sure to capture flight details
        - Each flight should have its own complete set of details
        - Store the duration in the format "Xh Ym" (e.g., "2h 15m")
        - Return the total price of the flight.
        - Make sure you include origin and destination airport names in the output.
        - Include the layover airports names and durations in the output (if there's any).
        - Don't do anything else, other than what is mentioned above.
    """
