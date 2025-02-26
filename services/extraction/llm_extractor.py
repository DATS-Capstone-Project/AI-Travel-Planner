import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from openai import OpenAI
from config.settings import OPENAI_API_KEY, EXTRACTION_MODEL
from services.extraction.extractor_interface import EntityExtractor
from models.trip_details import TripDetails
from utils.date_utils import validate_future_date

# Configure logger
logger = logging.getLogger(__name__)


class LLMEntityExtractor(EntityExtractor):
    """Uses OpenAI's API to extract entities from natural language with improved accuracy"""

    def __init__(self, fallback_extractor: Optional[EntityExtractor] = None):
        """
        Initialize the LLM extractor

        Args:
            fallback_extractor: Optional fallback extractor to use if LLM extraction fails
        """
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.fallback_extractor = fallback_extractor

    def extract(self, message: str, existing_details: Optional[TripDetails] = None) -> TripDetails:
        """
        Extract travel details using OpenAI API with context awareness

        Args:
            message: User message text
            existing_details: Optional existing trip details for context

        Returns:
            TripDetails object with extracted information
        """
        try:
            # Create system prompt for precise entity extraction
            system_prompt = """You are a precise travel information extraction system designed to extract structured data from natural language.
Your ONLY purpose is to extract specific travel details and return them in JSON format.
You must be extremely accurate, especially with dates, numbers, and ordinals.

IMPORTANT: For vague time references like "next week" or "next month", set start_date and end_date to null. 
DO NOT calculate specific dates for vague references."""

            # Build context from existing details if available
            context_str = ""
            if existing_details and any(value is not None for value in existing_details.__dict__.items()):
                # Filter out None values and confidence_levels for cleaner context
                existing_data = {k: v for k, v in existing_details.__dict__.items()
                                 if k != 'confidence_levels' and v is not None}
                context_str = f"""IMPORTANT CONTEXT - The user has previously provided these details:
{json.dumps(existing_data, indent=2)}

If the current message MODIFIES previous information, prefer the NEW information as it likely represents a correction."""

            # Create detailed extraction prompt with today's date for relative date calculation
            today = datetime.now()

            extraction_prompt = f"""{context_str}
Extract ONLY the following travel information from the user's message:

1. destination: The specific city or location the user wants to visit
   - Return the full, proper name of the destination

2. start_date: Convert any SPECIFIC date mention to YYYY-MM-DD format
   - Pay EXTREME attention to ordinal numbers (1st → 01, 2nd → 02, 3rd → 03, etc.)
   - If month is mentioned without year, use {today.year}
   - For "tomorrow", use {(today + timedelta(days=1)).strftime('%Y-%m-%d')}
   - IMPORTANT: For vague references like "next week" or "next month", use null

3. end_date: Convert to YYYY-MM-DD format OR calculate based on duration
   - If user mentions "X days/nights" calculate: start_date + (X-1) days
   - If user mentions "until" or "to" a specific date, use that date
   - IMPORTANT: For vague references like "next week" or "next month", use null

4. travelers: The TOTAL number of people traveling, including the user
   - If user says "with X people/friends/family" → total is X+1
   - If user says "X of us" or "total of X" → total is X
   - Pay attention to context to avoid double-counting

5. budget: Extract any mentioned budget amount in USD as integer
   - Look for numbers near words like "budget", "spend", "cost"
   - If a range is given, use the average

6. preferences: Extract activity preferences, interests or requirements
   - Include mentioned activities, sightseeing interests, special requirements
   - Multiple preferences should be separated by commas

7. date_reference: Include this special field ONLY IF user uses vague date terms
   - If message contains "next week", set to "next_week"
   - If message contains "next month", set to "next_month" 
   - If message contains "this weekend", set to "this_weekend"
   - Otherwise, leave as null

EXTRACTION RULES:
- Extract ONLY what is explicitly stated in THIS message
- For each field, if no relevant information exists, set to null
- NEVER invent or assume information not present in the message
- Be extremely precise with date formats (YYYY-MM-DD)
- Be especially careful with ordinal numbers in dates (1st, 2nd, 3rd, etc.)
- ALWAYS set date fields to null for vague references and use date_reference instead

EXAMPLES:
"I want to visit Paris in June for a week"
→ {{"destination": "Paris", "start_date": "{today.year}-06-01", "end_date": "{today.year}-06-07", "travelers": null, "budget": null, "preferences": null, "date_reference": null}}

"I wanna visit bangalore next week"
→ {{"destination": "Bangalore", "start_date": null, "end_date": null, "travelers": null, "budget": null, "preferences": null, "date_reference": "next_week"}}

"I want to go to Tokyo on March 1st for 9 days"
→ {{"destination": "Tokyo", "start_date": "{today.year}-03-01", "end_date": "{today.year}-03-09", "travelers": null, "budget": null, "preferences": null, "date_reference": null}}

"Me and my wife"
→ {{"destination": null, "start_date": null, "end_date": null, "travelers": 2, "budget": null, "preferences": null, "date_reference": null}}

User message: {message}"""

            # Call API with improved prompt and lower temperature for consistency
            response = self.client.chat.completions.create(
                model=EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": extraction_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1  # Lower temperature for more consistent results
            )

            # Parse the JSON response
            extracted_data = json.loads(response.choices[0].message.content)
            logger.info(f"LLM extraction result: {json.dumps(extracted_data)}")

            # Check for date references that need special handling
            date_reference = extracted_data.pop("date_reference", None)

            # Validate extracted data against existing details
            if existing_details:
                extracted_data = self._validate_against_existing(extracted_data, existing_details)

            # Clean and validate the extracted data
            cleaned_data = self._clean_extracted_data(extracted_data, message, date_reference)

            # Create TripDetails from extracted data
            return TripDetails(**cleaned_data)

        except Exception as e:
            logger.error(f"LLM extraction failed: {str(e)}")

            # Use fallback extractor if available
            if self.fallback_extractor:
                logger.info("Using fallback extraction method")
                return self.fallback_extractor.extract(message)

            # Return empty details if no fallback
            return TripDetails()

    def _validate_against_existing(self, new_data: Dict[str, Any], existing: TripDetails) -> Dict[str, Any]:
        """
        Validate new extraction against existing details to catch errors

        Args:
            new_data: Newly extracted data
            existing: Existing trip details

        Returns:
            Validated data with conflicts resolved
        """
        validated = new_data.copy()

        # Check for date confusion (e.g., 1st becoming 12th)
        if new_data.get("start_date") and existing.start_date and new_data["start_date"] != existing.start_date:
            # Log potential conflict
            logger.warning(f"Date conflict detected: {existing.start_date} vs {new_data['start_date']}")

            # Check if this looks like an ordinal confusion (e.g., 1st → 12th)
            # For example, if existing is "2025-03-01" and new is "2025-03-12" but user mentioned "1st"
            if (existing.start_date and
                    existing.start_date.endswith('01') and
                    new_data["start_date"] and
                    new_data["start_date"].endswith('12')):
                # Likely an error, keep existing
                validated["start_date"] = existing.start_date
                logger.info(f"Corrected likely ordinal confusion: keeping {existing.start_date}")

        # Only update fields that are explicitly mentioned in the new message
        for field, value in list(validated.items()):
            if value is None and hasattr(existing, field) and getattr(existing, field) is not None:
                validated[field] = getattr(existing, field)

        return validated

    def _clean_extracted_data(self, data: Dict[str, Any], message: str, date_reference: Optional[str] = None) -> Dict[
        str, Any]:
        """
        Clean and validate the extracted data

        Args:
            data: Raw extracted data from LLM
            message: Original user message
            date_reference: Optional date reference type (next_week, next_month, etc.)

        Returns:
            Cleaned and validated data dictionary
        """
        # Create a new dict to avoid modifying the input
        cleaned = {}
        confidence_levels = {}

        # Clean up destination
        if data.get("destination"):
            cleaned["destination"] = data["destination"].strip().title()

        # Validate dates and track confidence
        if data.get("start_date"):
            cleaned["start_date"] = validate_future_date(data["start_date"])

        if data.get("end_date"):
            cleaned["end_date"] = validate_future_date(data["end_date"])

        # Handle date references and set confidence levels
        if date_reference:
            logger.info(f"Detected vague date reference: {date_reference}")

            # Mark specific date references as needing confirmation
            if date_reference == "next_week":
                # Calculate dates for next week but mark as inferred
                today = datetime.now()
                next_week_start = today + timedelta(days=(7 - today.weekday()))
                next_week_end = next_week_start + timedelta(days=6)

                cleaned["start_date"] = next_week_start.strftime("%Y-%m-%d")
                cleaned["end_date"] = next_week_end.strftime("%Y-%m-%d")

                confidence_levels["start_date"] = "inferred"
                confidence_levels["end_date"] = "inferred"

            elif date_reference == "next_month":
                # Calculate dates for next month but mark as inferred
                today = datetime.now()
                next_month = today.replace(month=today.month + 1 if today.month < 12 else 1,
                                           year=today.year if today.month < 12 else today.year + 1,
                                           day=1)
                next_month_end = (next_month.replace(month=next_month.month + 1 if next_month.month < 12 else 1,
                                                     year=next_month.year if next_month.month < 12 else next_month.year + 1) -
                                  timedelta(days=1))

                cleaned["start_date"] = next_month.strftime("%Y-%m-%d")
                cleaned["end_date"] = next_month_end.strftime("%Y-%m-%d")

                confidence_levels["start_date"] = "inferred"
                confidence_levels["end_date"] = "inferred"

            elif date_reference == "this_weekend":
                # Calculate dates for this weekend but mark as inferred
                today = datetime.now()
                days_until_saturday = (5 - today.weekday()) % 7
                saturday = today + timedelta(days=days_until_saturday)
                sunday = saturday + timedelta(days=1)

                cleaned["start_date"] = saturday.strftime("%Y-%m-%d")
                cleaned["end_date"] = sunday.strftime("%Y-%m-%d")

                confidence_levels["start_date"] = "inferred"
                confidence_levels["end_date"] = "inferred"

        # Ensure travelers is an integer
        if data.get("travelers"):
            try:
                cleaned["travelers"] = int(data["travelers"])
            except (ValueError, TypeError):
                pass

        # Ensure budget is an integer
        if data.get("budget"):
            try:
                cleaned["budget"] = int(data["budget"])
            except (ValueError, TypeError):
                pass

        # Clean up preferences
        if data.get("preferences"):
            cleaned["preferences"] = data["preferences"].strip()

        # Add confidence levels to the result
        cleaned["confidence_levels"] = confidence_levels

        return cleaned