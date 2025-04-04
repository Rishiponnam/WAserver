import os
import json
import requests
import logging
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_session import Session
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
Session(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://api.heltar.com/v1/messages/send"
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN")
user_sessions = {}

def send_whatsapp_message(recipient_number, message_text=None, message_type="text"):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }

    message = {
        "clientWaNumber": recipient_number,
        "messageType": message_type,
    }

    if message_type == "text":
        message["message"] = message_text or "Hello from server"
    
    elif message_type == "buttons":
        message["interactive"] = {
            "type": "button",
            "body": {
                "text": message_text or "Choose an option"
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "1", "title": "1"}},
                    {"type": "reply", "reply": {"id": "2", "title": "2"}},
                    {"type": "reply", "reply": {"id": "3", "title": "3"}},
                    {"type": "reply", "reply": {"id": "4", "title": "4"}},
                    {"type": "reply", "reply": {"id": "5", "title": "5"}},
                ]
            }
        }

    else:
        message["message"] = message_text or "Fallback message"

    payload = {"messages": [message]}
    logger.info(f"Sending message: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        logger.info(f"Response: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error sending message: {e}")

def process_message(sender_id, message_text):
    logger.info(f"Received message from {sender_id}: {message_text}")

    # Initialize session if not exists
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {
            "session_id": str(uuid.uuid4()),
            "created_at": datetime.now(),
            "last_interaction": datetime.now(),
            "conversation_state": "greeting"
        }
        logger.info(f"New user session started for {sender_id}.")
        send_whatsapp_message(sender_id, "Hello! Welcome to our service. How can I help you today?")
        return  

    # Update last interaction
    user_sessions[sender_id]["last_interaction"] = datetime.now()
    state = user_sessions[sender_id]["conversation_state"]
    logger.info(f"Current state for {sender_id}: {state}")

    # Transition from greeting to menu
    if state == "greeting":
        logger.info(f"Moving {sender_id} to 'menu' state.")
        user_sessions[sender_id]["conversation_state"] = "menu"
        send_whatsapp_message(sender_id, "Please select an option below:", message_type="buttons")
        return  

    elif state == "menu":
        logger.info(f"{sender_id} selected: {message_text}")

        if "option" in message_text.lower() or "menu" in message_text.lower():
            send_whatsapp_message(sender_id, "Please select an option below:", message_type="buttons")

        elif message_text in ["1", "2", "3", "4", "5"]:
            handle_option_selection(sender_id, message_text)
        else:
            send_whatsapp_message(sender_id, "Invalid option. Please choose from the buttons.", message_type="buttons")
        return  

    # Restart session if something goes wrong
    logger.warning(f"Unexpected state '{state}' for {sender_id}. Restarting session.")
    user_sessions[sender_id]["conversation_state"] = "greeting"
    send_whatsapp_message(sender_id, "Let's start over. How can I assist you?")

def handle_option_selection(sender_id, option):
    if option == "1":
        send_whatsapp_message(sender_id, "Here is your first image!", message_type="image")
    elif option == "2":
        send_whatsapp_message(sender_id, "Here is your second image!", message_type="image")
    elif option == "3":
        send_whatsapp_message(sender_id, message_type="location")
    elif option == "4":
        send_whatsapp_message(sender_id, message_type="contact")
    elif option == "5":
        send_whatsapp_message(sender_id, "Here’s a normal text message.")

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"📥 Received webhook: {json.dumps(data, indent=2)}")

        if 'entry' in data:
            for entry in data['entry']:
                for change in entry.get('changes', []):
                    for message in change.get('value', {}).get('messages', []):
                        sender_id = message['from']
                        message_text = message.get('text', {}).get('body', '')

                        if sender_id and message_text:
                            process_message(sender_id, message_text)

        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        "status": "active",
        "active_sessions": len(user_sessions),
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)