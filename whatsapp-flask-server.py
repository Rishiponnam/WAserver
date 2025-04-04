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

def send_whatsapp_message(payload):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        logger.info(f"Message sent. Response: {response.text}")
        return response.json()
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        return None

def send_text_message(recipient_number, message_text):
    payload = {
        "messages": [{
            "clientWaNumber": recipient_number,
            "message": message_text,
            "messageType": "text"
        }]
    }
    return send_whatsapp_message(payload)

def send_button_message(recipient_number, message_text, buttons):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }
    payload = {
        "clientWaNumber": recipient_number,
        "messageType": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": message_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": btn["id"], "title": btn["title"]}
                    }
                    for btn in buttons
                ]
            }
        }
    }
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        logger.info(f"Message sent to {recipient_number}. Response: {response.text}")
        return response.json()
    except Exception as e:
        logger.error(f"Error sending WhatsApp buttons: {str(e)}")
        return None

def send_media_message(recipient_number, media_url, caption, media_type="image"):
    payload = {
        "messages": [{
            "clientWaNumber": recipient_number,
            "message": caption,
            "messageType": media_type,
            "mediaUrl": media_url
        }]
    }
    return send_whatsapp_message(payload)

def process_message(sender_id, message_text):
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {
            "session_id": str(uuid.uuid4()),
            "created_at": datetime.now(),
            "last_interaction": datetime.now(),
            "conversation_state": "greeting",
            "context": {}
        }
        return send_button_message(sender_id, "Welcome! Choose an option:", [
            {"id": "1", "title": "Product Info"},
            {"id": "2", "title": "Customer Support"},
            {"id": "3", "title": "Place an Order"}
        ])
    
    user_sessions[sender_id]["last_interaction"] = datetime.now()
    state = user_sessions[sender_id]["conversation_state"]
    
    if state == "greeting":
        user_sessions[sender_id]["conversation_state"] = "menu"
        return send_button_message(sender_id, "What would you like to do?", [
            {"id": "1", "title": "Product Info"},
            {"id": "2", "title": "Customer Support"},
            {"id": "3", "title": "Place an Order"}
        ])
    elif state == "menu":
        if "1" in message_text or "product" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "product_info"
            return send_media_message(sender_id, "https://www.google.co.in/imgres?q=random%20photos%20of%20things&imgurl=https%3A%2F%2Fimages.pexels.com%2Fphotos%2F9304725%2Fpexels-photo-9304725.jpeg%3Fcs%3Dsrgb%26dl%3Dpexels-jj-jordan-44924743-9304725.jpg%26fm%3Djpg&imgrefurl=https%3A%2F%2Fwww.pexels.com%2Fsearch%2Frandom%2520objects%2F&docid=fWWQgzUAPejkDM&tbnid=c25_s8kVWDGc-M&vet=12ahUKEwja1PzA1r2MAxWfh68BHW45BIMQM3oECGsQAA..i&w=3681&h=4601&hcb=2&ved=2ahUKEwja1PzA1r2MAxWfh68BHW45BIMQM3oECGsQAA", "Check out our latest product!")
        elif "2" in message_text or "support" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "support"
            send_text_message(sender_id, "Please describe your issue.")
        elif "3" in message_text or "order" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "order"
            send_text_message(sender_id, "Please provide product name and quantity.")
        else:
            send_text_message(sender_id, "Invalid option. Please reply with 1, 2, or 3.")

    logger.info(f"Processing message from {sender_id}: {message_text}")
    
@app.route('/')
def home():
    return jsonify({"message": "WhatsApp Flask Server is Running!"})

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"Received webhook raw data: {json.dumps(data, indent=2)}")
        if 'entry' in data:
            for entry in data['entry']:
                for change in entry.get('changes', []):
                    for message in change.get('value', {}).get('messages', []):
                        if message['type'] == 'text':
                            sender_id = message['from']
                            message_text = message['text']['body']
                            process_message(sender_id, message_text)
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