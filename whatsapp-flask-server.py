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

def send_whatsapp_message(recipient_number, message_text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }
    payload = {
        "messages": [{
            "clientWaNumber": recipient_number,
            "message": message_text,
            "messageType": "text"
        }]
    }
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        logger.info(f"Message sent to {recipient_number}. Response: {response.text}")
        return response.json()
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        return None

def process_message(sender_id, message_text):
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {
            "session_id": str(uuid.uuid4()),
            "created_at": datetime.now(),
            "last_interaction": datetime.now(),
            "conversation_state": "greeting",
            "context": {}
        }
        return "Hello! Welcome to our service. How can I help you today?"
    
    user_sessions[sender_id]["last_interaction"] = datetime.now()
    state = user_sessions[sender_id]["conversation_state"]
    
    if state == "greeting":
        user_sessions[sender_id]["conversation_state"] = "menu"
        return "I'm here to assist you. What would you like to do?\n1. Product Information\n2. Customer Support\n3. Place an Order"
    
    elif state == "menu":
        if "1" in message_text or "product" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "product_info"
            return "Our latest products include Model A, Model B, and Model C. Which one would you like to know more about?"
        elif "2" in message_text or "support" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "support"
            return "Please describe the issue you're experiencing."
        elif "3" in message_text or "order" in message_text.lower():
            user_sessions[sender_id]["conversation_state"] = "order"
            return "To place an order, please provide your product choice and quantity."
        return "Invalid option. Please reply with 1, 2, or 3."
    
    elif state == "product_info":
        products = {"a": "Model A - $299", "b": "Model B - $199", "c": "Model C - $99"}
        for key, description in products.items():
            if key in message_text.lower():
                user_sessions[sender_id]["context"]["product_interest"] = key
                user_sessions[sender_id]["conversation_state"] = "product_followup"
                return f"{description}\n\nWould you like to place an order?"
        return "Please specify Model A, B, or C."
    
    elif state == "support":
        user_sessions[sender_id]["context"]["support_issue"] = message_text
        user_sessions[sender_id]["conversation_state"] = "support_processing"
        return "Our support team will review your issue and get back to you."
    
    elif state == "order":
        try:
            quantity = int(''.join(filter(str.isdigit, message_text)))
            if quantity > 0:
                user_sessions[sender_id]["context"]["order_quantity"] = quantity
                user_sessions[sender_id]["conversation_state"] = "order_confirmation"
                return "Please provide your delivery address."
        except:
            return "Please enter a valid quantity."
    
    elif state == "order_confirmation":
        user_sessions[sender_id]["context"]["delivery_address"] = message_text
        user_sessions[sender_id]["conversation_state"] = "order_complete"
        return "Thank you! Your order has been placed."
    
    user_sessions[sender_id]["conversation_state"] = "greeting"
    return "Let's start over. How can I assist you?"

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