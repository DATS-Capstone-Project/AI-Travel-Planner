import streamlit as st
import requests
import uuid
from datetime import datetime

# Configure API URL
API_URL = "http://127.0.0.1:8000"

# Page setup
st.set_page_config(
    page_title="AI Travel Planner",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Simple CSS that works well in both light and dark mode
st.markdown("""
<style>
    .user-msg {
        background-color: rgba(70, 130, 180, 0.2);
        padding: 10px 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border-left: 4px solid #4682b4;
    }
    .assistant-msg {
        background-color: rgba(46, 139, 87, 0.2);
        padding: 10px 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border-left: 4px solid #2e8b57;
    }
    .travel-title {
        font-size: 24px;
        font-weight: bold;
        display: flex;
        align-items: center;
    }
    .travel-emoji {
        font-size: 28px;
        margin-right: 10px;
    }
</style>
""", unsafe_allow_html=True)


def chat_with_bot(session_id, message):
    """Send message to backend API and get response"""
    try:
        response = requests.post(
            f"{API_URL}/chat",
            json={"session_id": session_id, "message": message},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error communicating with the server: {str(e)}")
        return {"response": "Sorry, I'm having trouble connecting to the server. Please try again later."}


def reset_session(session_id):
    """Reset session on the backend"""
    try:
        requests.post(f"{API_URL}/reset/{session_id}")
        return True
    except:
        return False


def main():
    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "trip_details" not in st.session_state:
        st.session_state.trip_details = {}

    # Layout: Two columns, sidebar for trip details, main column for chat
    with st.sidebar:
        # Title in sidebar
        st.markdown('<div class="travel-title"><span class="travel-emoji">✈️</span>Trip Details</div>',
                    unsafe_allow_html=True)

        # Trip details display
        # Trip details display
        st.write("As I understand them so far:")

        if st.session_state.trip_details:
            details = st.session_state.trip_details

            if details.get("destination"):
                st.markdown(f"**Destination:** {details['destination']}")
            if details.get("origin"):
                st.markdown(f"**Origin:** {details['origin']}")
            else:
                st.markdown("**Origin:** *Not provided (Required)*")

            if details.get("start_date") and details.get("end_date"):
                st.markdown(f"**Dates:** {details['start_date']} to {details['end_date']}")
            elif details.get("start_date"):
                st.markdown(f"**Start Date:** {details['start_date']}")

            if details.get("travelers"):
                st.markdown(f"**Travelers:** {details['travelers']}")

            if details.get("budget"):
                st.markdown(f"**Budget:** ${details['budget']}")

            if details.get("preferences"):
                st.markdown(f"**Preferences:** {details['preferences']}")
        else:
            st.info("No trip details yet. Start chatting to plan your trip!")

        st.divider()

        # Reset button
        if st.button("Start New Trip"):
            reset_session(st.session_state.session_id)
            st.session_state.messages = []
            st.session_state.trip_details = {}
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()

    # Main chat area
    st.markdown('<div class="travel-title"><span class="travel-emoji">✈️</span>AI Travel Planner</div>',
                unsafe_allow_html=True)
    st.write("Your personal AI-powered travel assistant")

    # Welcome message if no messages
    if not st.session_state.messages:
        st.info("""
        👋 Hi there! I'm your AI travel planner. Tell me about your trip, and I'll help you organize it.

        Try saying something like:
        - "I want to visit Paris for a week in June"
        - "Planning a trip to Japan with my family of 4"
        - "Looking for beach activities in Bali"
        """)

    # Display chat messages
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f'<div class="user-msg">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="assistant-msg">{msg["content"]}</div>', unsafe_allow_html=True)

    # Chat input
    user_input = st.chat_input("What are your travel plans?")
    if user_input:
        # Add user message to history
        st.session_state.messages.append({"role": "user", "content": user_input})

        # Get response from backend
        with st.spinner("Planning your trip..."):
            response_data = chat_with_bot(st.session_state.session_id, user_input)
            response_text = response_data.get("response", "Sorry, I couldn't process that request.")

            # Update trip details if available
            if "extracted_data" in response_data and response_data["extracted_data"]:
                st.session_state.trip_details = response_data["extracted_data"]

        # Add assistant response to history
        st.session_state.messages.append({"role": "assistant", "content": response_text})

        # Rerun to update the UI
        st.rerun()


if __name__ == "__main__":
    main()