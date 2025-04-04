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

    elif message_type == "image":
        message["message"] = {
            "url": "https://via.placeholder.com/300",  # replace with real URL
            "caption": "Here's an image"
        }

    elif message_type == "location":
        message["message"] = {
            "latitude": "37.422", 
            "longitude": "-122.084", 
            "name": "Google HQ"
        }

    elif message_type == "contact":
        message["message"] = {
            "contacts": [
                {
                    "name": {"firstName": "Support", "lastName": "Team"},
                    "phones": [{"phone": "+1234567890"}],
                }
            ]
        }

    elif message_type == "document":
        message["message"] = {
            "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
            "filename": "sample.pdf",
            "caption": "Download this document"
        }

    else:
        message["message"] = message_text or "Unsupported message type"

    payload = {"messages": [message]}

    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        logger.info(f"Message sent to {recipient_number}: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")

def process_message(sender_id, message_text):
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {
            "session_id": str(uuid.uuid4()),
            "created_at": datetime.now(),
            "last_interaction": datetime.now(),
        }
        send_whatsapp_message(sender_id, "Hello! Please choose an option:", message_type="buttons")
        return

    user_sessions[sender_id]["last_interaction"] = datetime.now()

    if message_text == "1":
        send_whatsapp_message(sender_id, "", message_type="image")
    elif message_text == "2":
        send_whatsapp_message(sender_id, "", message_type="image2")
    elif message_text == "3":
        send_whatsapp_message(sender_id, "", message_type="location")
    elif message_text == "4":
        send_whatsapp_message(sender_id, "", message_type="contact")
    elif message_text == "5":
        send_whatsapp_message(sender_id, "This is a normal text message.")
    else:
        send_whatsapp_message(sender_id, "Please choose a valid option:", message_type="buttons")

@app.route('/')
def home():
    return jsonify({"message": "WhatsApp Flask Server is Running!"})

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Received webhook data: {json.dumps(data)}")
        if 'entry' in data:
            for entry in data['entry']:
                for change in entry.get('changes', []):
                    for message in change.get('value', {}).get('messages', []):
                        if message['type'] == 'text':
                            sender_id = message['from']
                            message_text = message['text']['body']
                            logger.info(f"Incoming message from {sender_id}: {message_text}")
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