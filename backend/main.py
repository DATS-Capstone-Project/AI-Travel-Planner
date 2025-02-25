from fastapi import FastAPI, HTTPException
from models import ChatRequest, ChatResponse
from state_manager import state_manager
from agents import flight_agent, hotel_agent, activity_agent
from utils import parse_date, validate_dates, extract_trip_details
from openai import OpenAI
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import re

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()


def generate_contextual_prompt(session: dict) -> str:
    """Generate context-aware prompt based on collected information"""
    collected = []
    missing = []

    confirmation_phrases = ["confirm", "yes", "correct", "right"]
    negation_phrases = ["no", "wrong", "incorrect", "change"]

    # Handle confirmation state
    if session.get("confirmation_asked"):
        if any(phrase in session.get("last_response", "").lower() for phrase in confirmation_phrases):
            return "All details confirmed. Generating itinerary..."
        if any(phrase in session.get("last_response", "").lower() for phrase in negation_phrases):
            session.update({"destination": None, "start_date": None,
                            "end_date": None, "travelers": None})
            return "Let's start over. Where would you like to go?"

    # Track collected and missing information
    fields = {
        "destination": "Destination",
        "start_date": "Start date",
        "end_date": "End date",
        "travelers": "Number of travelers"
    }

    for key, label in fields.items():
        if session.get(key):
            collected.append(f"{label}: {session[key]}")
        else:
            missing.append(label.lower())

    if not missing:
        session["confirmation_asked"] = True
        return f"Please confirm your trip to {session['destination']} from {session['start_date']} to {session['end_date']} for {session['travelers']} travelers. (yes/no)"

    prompt = "Continue the conversation naturally while "
    if collected:
        prompt += f"acknowledging these details: {', '.join(collected)}. "
    prompt += f"Ask for {missing[0]} in a friendly, conversational way."

    return prompt


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session = state_manager.get_session(request.session_id)
    user_message = request.message.lower()
    session["last_response"] = user_message

    # Extract entities from user message
    extracted = extract_trip_details(request.message)
    print(f"Extracted: {extracted}")
    # Update session with extracted values
    for key in ["destination", "start_date", "end_date", "travelers"]:
        if extracted.get(key):
            session[key] = extracted[key]

    # Handle duration (e.g., "5 days")
    if not session.get("end_date") and extracted.get("duration"):
        try:
            start_date = datetime.strptime(session["start_date"], "%Y-%m-%d")
            end_date = start_date + timedelta(days=extracted["duration"])
            session["end_date"] = end_date.strftime("%Y-%m-%d")
        except:
            pass

    # Generate contextual prompt
    prompt = generate_contextual_prompt(session)
    print(f"Prompt: {prompt}")
    print(f"Request: {request.message}")
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": request.message},
            ],
            temperature=0.7
        )
        bot_response = response.choices[0].message.content
    except Exception as e:
        return ChatResponse(response="I'm having trouble processing that. Could you please rephrase?")

    # Generate itinerary after confirmation
    if "generating itinerary" in bot_response.lower():
        try:
            if not validate_dates(session["start_date"], session["end_date"]):
                return ChatResponse(response="Please check your dates - end date should be after start date.")

            flights = flight_agent.get_flights(session["destination"],
                                               session["start_date"],
                                               session["travelers"])
            hotels = hotel_agent.get_hotels(session["destination"],
                                            session["start_date"],
                                            session["end_date"],
                                            session.get("budget", 1000))
            activities = activity_agent.get_activities(session["destination"],
                                                       session.get("preferences", ""))

            itinerary = (f"Here's your trip plan:\n✈️ {flights}\n"
                         f"🏨 {hotels}\n🎡 {activities}")

            # Reset session after itinerary generation
            state_manager.clear_session(request.session_id)
            return ChatResponse(response=itinerary)
        except Exception as e:
            return ChatResponse(response="I'm having trouble generating your itinerary. Please try again later.")

    return ChatResponse(response=bot_response)