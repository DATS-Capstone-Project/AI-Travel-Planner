import streamlit as st
import requests

# Backend URL
BACKEND_URL = "http://127.0.0.1:8000"


def chat_with_bot(session_id: str, message: str) -> str:
    try:
        response = requests.post(
            f"{BACKEND_URL}/chat",
            json={"session_id": session_id, "message": message},
        )
        # Check if the response is successful (status code 200)
        response.raise_for_status()
        # Parse JSON response
        return response.json()["response"]
    except requests.exceptions.RequestException as e:
        # Log the error and return a user-friendly message
        st.error(f"Error communicating with the backend: {e}")
        return "Sorry, something went wrong. Please try again later."
    except ValueError as e:
        # Log the error and return a user-friendly message
        st.error(f"Invalid response from the backend: {e}")
        return "Sorry, the backend returned an invalid response."


def main():
    st.title("AI Travel Planner")

    # Initialize session state
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = "user123"
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Display chat history
    for msg in st.session_state["messages"]:
        st.write(f"{msg['role']}: {msg['text']}")

    # User input
    user_input = st.text_input("You:", key="user_input", value="")
    if user_input:
        # Add user input to chat history
        st.session_state["messages"].append({"role": "user", "text": user_input})

        # Get bot response
        bot_response = chat_with_bot(st.session_state["session_id"], user_input)

        # Add bot response to chat history
        st.session_state["messages"].append({"role": "bot", "text": bot_response})

        # Rerun the app to display the updated chat history
        st.rerun()


if __name__ == "__main__":
    main()