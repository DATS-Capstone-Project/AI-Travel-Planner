import re
import logging
from datetime import datetime, timedelta
from services.extraction.extractor_interface import EntityExtractor
from models.trip_details import TripDetails
from utils.date_utils import parse_date, validate_future_date

# Configure logger
logger = logging.getLogger(__name__)


class RegexEntityExtractor(EntityExtractor):
    """
    Uses regular expressions to extract entities from natural language
    This serves as a fallback if the LLM extraction fails
    """

    def extract(self, message: str) -> TripDetails:
        """
        Extract travel details using regex patterns

        Args:
            message: User message text

        Returns:
            TripDetails object with extracted information
        """
        logger.info("Using regex-based entity extraction")
        details_dict = self._extract_trip_details(message)
        return TripDetails(**details_dict)

    def _extract_trip_details(self, message: str) -> dict:
        """Extract travel details from natural language message"""
        details = {}
        message = message.lower()

        # Extract destination
        destination_patterns = [
            r'(?:to|in|visit|going to|travel to|trip to)\s+([a-z\s]+)(?:\s+(?:from|in|on|for|with))',
            r'(?:to|in|visit|going to|travel to|trip to)\s+([a-z\s]+)(?:$|\.)'
        ]

        for pattern in destination_patterns:
            match = re.search(pattern, message)
            if match:
                details['destination'] = match.group(1).strip().title()
                break

        # Extract traveler information
        traveler_patterns = [
            r'(\d+)\s+(?:people|travelers|persons|adults)',
            r'(?:we are|we\'re)\s+(?:a group of|a family of)?\s*(\d+)',
            r'(?:with|and)\s+(\d+)\s+(?:other|more)\s+(?:people|friends|family|travelers)',
            r'(?:total of|group of)\s+(\d+)\s+(?:people|travelers|persons)'
        ]

        for pattern in traveler_patterns:
            match = re.search(pattern, message)
            if match:
                count = int(match.group(1))
                # If "with X other people", add 1 for the user
                if "other" in pattern:
                    count += 1
                details['travelers'] = count
                break

        # If mentioning "with X other people", add 1 for the user
        if "with" in message and "other" in message:
            other_match = re.search(r'with\s+(\d+)\s+other', message)
            if other_match:
                details['travelers'] = int(other_match.group(1)) + 1

        # Extract dates
        date_patterns = [
            # Specific date formats
            r'(?:from|on|starting)\s+((?:\d{1,2}(?:st|nd|rd|th)?\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{2,4})?)',
            r'(?:until|to|ending|through)\s+((?:\d{1,2}(?:st|nd|rd|th)?\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{2,4})?)',
            # ISO format
            r'(\d{4}-\d{2}-\d{2})'
        ]

        dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, message)
            dates.extend(matches)

        # Process found dates
        parsed_dates = []
        for date_str in dates:
            parsed = parse_date(date_str)
            if parsed:
                parsed_dates.append(parsed)

        # Assign start and end dates if available
        if parsed_dates:
            parsed_dates.sort()  # Sort dates chronologically
            details['start_date'] = parsed_dates[0]
            if len(parsed_dates) > 1:
                details['end_date'] = parsed_dates[1]

        # Extract duration if dates are incomplete
        if ('start_date' in details and 'end_date' not in details) or (
                'start_date' not in details and 'end_date' not in details):
            duration_match = re.search(r'(?:for|planning)\s+(\d+)\s+(?:days|nights)', message)
            if duration_match:
                duration = int(duration_match.group(1))
                if 'start_date' in details:
                    # Calculate end date based on start date and duration
                    start = datetime.strptime(details['start_date'], "%Y-%m-%d")
                    end = start + timedelta(days=duration)
                    details['end_date'] = end.strftime("%Y-%m-%d")
                elif 'end_date' not in details:
                    # Suggest dates starting from 2 weeks from now
                    suggested_start = datetime.now() + timedelta(days=14)
                    suggested_end = suggested_start + timedelta(days=duration)
                    details['start_date'] = suggested_start.strftime("%Y-%m-%d")
                    details['end_date'] = suggested_end.strftime("%Y-%m-%d")

        # Extract budget information (optional)
        budget_match = re.search(r'budget\s+(?:of|is|:)?\s*(?:USD|€|£|\$|€|£)?(\d+(?:,\d+)?)', message)
        if budget_match:
            # Remove commas and convert to integer
            budget_str = budget_match.group(1).replace(',', '')
            details['budget'] = int(budget_str)

        # Extract activity preferences (optional)
        activity_patterns = [
            r'(?:interested in|looking for|want to do|activities like|activities such as|prefer)\s+([^.?!]+)'
        ]

        for pattern in activity_patterns:
            match = re.search(pattern, message)
            if match:
                details['preferences'] = match.group(1).strip()
                break

        logger.info(f"Regex extraction results: {details}")
        return details