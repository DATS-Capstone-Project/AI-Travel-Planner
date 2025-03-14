from dotenv import load_dotenv, find_dotenv
import os

# Find and print the path to the .env file for debugging
dotenv_path = find_dotenv()
print(f"Found .env file at: {dotenv_path}")

# Load the .env file using the found path
load_dotenv(dotenv_path)

api_key = os.getenv("OPENAI_API_KEY")
print(f"OPENAI_API_KEY = {api_key}")
