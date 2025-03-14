import os
import json
from dotenv import load_dotenv, find_dotenv

# Locate and load the .env file
dotenv_path = find_dotenv()
if dotenv_path:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path)
else:
    print("Warning: .env file not found!")

# Get the API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("OPENAI_API_KEY is not set!")
else:
    print("DEBUG: OPENAI_API_KEY loaded successfully.")

# Import and initialize the new OpenAI client interface
from openai import OpenAI
client = OpenAI(api_key=api_key)

def parse_user_input_with_llm(user_input: str) -> dict:
    """
    Send the user_input to GPT and request a JSON structure with the trip details.
    Return a dictionary with any extracted fields or defaults if parsing fails.
    """
    system_prompt = """
    You are a helpful assistant that extracts the following information from the user's message if available:
    - destination (string)
    - origin (string)
    - start_date (string, in YYYY-MM-DD format)
    - end_date (string, in YYYY-MM-DD format)
    - travelers (integer)
    - budget (integer)
    - preferences (string)

    Return a JSON object with these keys exactly. If a field is missing, set it to null.
    Your entire response MUST be valid JSON, with no extra commentary.

    Example valid response:
    {
      "origin": "Mumbai"
      "destination": "Paris",
      "start_date": "2025-03-21",
      "end_date": "2025-03-23",
      "travelers": 2,
      "budget": 1500,
      "preferences": "culture"
    }
    """

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0,
        )
        # Debug: print raw response (optional)
        raw_content = response.choices[0].message.content.strip()
        print("DEBUG: Raw API response:", raw_content)
        data = json.loads(raw_content)
    except Exception as e:
        print("DEBUG: Exception during API call or JSON parsing:", e)
        data = {
            "origin": None,
            "destination": None,
            "start_date": None,
            "end_date": None,
            "travelers": None,
            "budget": None,
            "preferences": None,
        }
    return data
