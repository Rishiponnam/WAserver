import os
import json
import requests
import logging
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session
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
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")

user_sessions = {}

def send_whatsapp_message(recipient_number, message_text=None, message_type="text", extra=None):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }

    message_payload = {
        "clientWaNumber": recipient_number,
        "messageType": message_type
    }

    if message_type == "text":
        message_payload["message"] = message_text

    elif message_type == "image":
        message_payload["mediaUrl"] = "https://via.placeholder.com/512x512.png?text=Product+Image"
        message_payload["caption"] = message_text or "Here's an image for you!"

    elif message_type == "document":
        message_payload["mediaUrl"] = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        message_payload["filename"] = "order_details.pdf"
        message_payload["caption"] = "Order form attached."

    elif message_type == "location":
        message_payload["longitude"] = "78.4867"
        message_payload["latitude"] = "17.3850"
        message_payload["name"] = "Support Center"
        message_payload["address"] = "Hyderabad, India"

    elif message_type == "contact":
        message_payload["contacts"] = [{
            "name": {"formatted_name": "Support Agent"},
            "phones": [{"phone": "+919999999999", "type": "mobile"}]
        }]

    elif message_type == "buttons":
        message_payload["message"] = message_text or "Choose an option:"
        message_payload["buttons"] = [
            {"id": "product", "title": "Product Info"},
            {"id": "support", "title": "Customer Support"},
            {"id": "order", "title": "Place Order"}
        ]

    payload = {"messages": [message_payload]}

    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        logger.info(f"Interactive message sent to {recipient_number}. Response: {response.text}")
        return response.json()
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        return None


import random

def process_message(sender_id, message_text):
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {
            "session_id": str(uuid.uuid4()),
            "created_at": datetime.now(),
            "last_interaction": datetime.now(),
            "conversation_state": "greeting",
            "context": {}
        }
        send_whatsapp_message(sender_id, "Hello! Welcome to our service. How can I help you today?", message_type="buttons")
        return None

    user_sessions[sender_id]["last_interaction"] = datetime.now()
    state = user_sessions[sender_id]["conversation_state"]

    if state == "greeting":
        user_sessions[sender_id]["conversation_state"] = "menu"
        send_whatsapp_message(sender_id, "Please select an option below:", message_type="buttons")
        return None

    elif state == "menu":
        if "1" in message_text or "product" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "product_info"
            send_whatsapp_message(sender_id, "Check out this product!", message_type="image")
            return None
        elif "2" in message_text or "support" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "support"
            send_whatsapp_message(sender_id, message_type="location")
            return None
        elif "3" in message_text or "order" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "order"
            send_whatsapp_message(sender_id, message_type="document")
            return None
        send_whatsapp_message(sender_id, "Please tap on one of the buttons.", message_type="buttons")
        return None

    elif state == "product_info":
        send_whatsapp_message(sender_id, "Here's our support contact if you need help.", message_type="contact")
        return None

    elif state == "support":
        user_sessions[sender_id]["conversation_state"] = "done"
        return "Thanks for contacting support!"

    elif state == "order":
        user_sessions[sender_id]["conversation_state"] = "order_followup"
        return "Please reply with your delivery address."

    elif state == "order_followup":
        user_sessions[sender_id]["conversation_state"] = "done"
        return "Thanks! Your order is being processed."

    return "Let's start over. Type anything to begin again."


@app.route('/')
def home():
    return jsonify({"message": "WhatsApp Flask Server is Running!"})

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Received webhook data: {data}")
        if 'entry' in data:
            for entry in data['entry']:
                for change in entry.get('changes', []):
                    for message in change.get('value', {}).get('messages', []):
                        if message['type'] == 'text':
                            sender_id = message['from']
                            message_text = message['text']['body']
                            response_text = process_message(sender_id, message_text)
                            if response_text:
                                send_whatsapp_message(sender_id, response_text)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"status": "active", "active_sessions": len(user_sessions), "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)