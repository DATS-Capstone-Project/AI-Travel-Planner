import re
import logging
from datetime import datetime, timedelta
from typing import Optional
from dateutil.parser import parse as dateutil_parse
from config.settings import MAX_FUTURE_DAYS

# Configure logger
logger = logging.getLogger(__name__)


def parse_date(text: str) -> Optional[str]:
    """
    Parse date from text into YYYY-MM-DD format

    Args:
        text: Date string in any format

    Returns:
        Formatted date string or None if parsing fails
    """
    try:
        # If already in YYYY-MM-DD format, return as is
        if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            return text

        parsed_date = dateutil_parse(text)

        # If year is not specified in the input, use current year
        current_year = datetime.now().year
        if parsed_date.year == current_year and text.lower().find(str(current_year)) == -1:
            # If the date has already passed in current year, assume next year
            if parsed_date < datetime.now():
                parsed_date = parsed_date.replace(year=current_year + 1)

        return parsed_date.strftime("%Y-%m-%d")

    except Exception as e:
        logger.error(f"Error parsing date '{text}': {e}")
        return None


def validate_future_date(date_str: str) -> Optional[str]:
    """
    Validate a date string and ensure it's within allowed future range

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Validated date string or None if invalid
    """
    try:
        # Convert to datetime
        date = datetime.strptime(date_str, "%Y-%m-%d")

        # Ensure date is not in the past
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if date < today:
            logger.warning(f"Date {date_str} is in the past, adjusting to future")
            date = today + timedelta(days=14)  # Default to 2 weeks from now

        # Ensure date is not too far in the future
        max_future = today + timedelta(days=MAX_FUTURE_DAYS)
        if date > max_future:
            logger.warning(f"Date {date_str} is too far in future, adjusting to max allowed")
            date = max_future

        return date.strftime("%Y-%m-%d")

    except Exception as e:
        logger.error(f"Error validating date '{date_str}': {e}")
        return None


def validate_date_range(start_date: str, end_date: str) -> bool:
    """
    Validate that end date is after start date and both are within limits

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        True if date range is valid, False otherwise
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%D")

        # End must be after start
        if end <= start:
            return False

        # Check that dates are within allowed range
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        max_future = today + timedelta(days=MAX_FUTURE_DAYS)

        return start >= today and end <= max_future

    except Exception:
        return False


def calculate_duration(start_date: str, end_date: str) -> Optional[int]:
    """
    Calculate duration between two dates in days

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Number of days or None if calculation fails
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%D")
        end = datetime.strptime(end_date, "%Y-%m-%D")
        return (end - start).days
    except Exception:
        return None