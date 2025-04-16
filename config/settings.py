import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# OpenAI API settings
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EXTRACTION_MODEL = "gpt-4.1-mini"  # Faster model for entity extraction
CONVERSATION_MODEL = "gpt-4.1-mini"  # Model for the assistant
SERP_API_KEY = os.getenv("SERP_API_KEY")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

# Travel planning settings
MAX_FUTURE_DAYS = 180  # Maximum days in future for booking (6 months)
DEFAULT_BUDGET = 1000  # Default budget per night if not specified

# Assistant settings
ASSISTANT_NAME = "Travel Planner"

# Logging settings
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'