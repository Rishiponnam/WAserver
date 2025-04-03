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
        return {
            "to": sender_id,
            "messages": [{
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": "Hello! Welcome to our service. How can I help you today?"},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "menu_1", "title": "Product Info"}},
                            {"type": "reply", "reply": {"id": "menu_2", "title": "Customer Support"}},
                            {"type": "reply", "reply": {"id": "menu_3", "title": "Place Order"}}
                        ]
                    }
                }
            }]
        }

    user_sessions[sender_id]["last_interaction"] = datetime.now()
    state = user_sessions[sender_id]["conversation_state"]

    if state == "greeting":
        user_sessions[sender_id]["conversation_state"] = "menu"
        return {
            "to": sender_id,
            "messages": [{
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": "I'm here to assist you. What would you like to do?"},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "menu_1", "title": "Product Info"}},
                            {"type": "reply", "reply": {"id": "menu_2", "title": "Customer Support"}},
                            {"type": "reply", "reply": {"id": "menu_3", "title": "Place Order"}}
                        ]
                    }
                }
            }]
        }

    elif state == "menu":
        if message_text in ["menu_1", "1", "Product Info"]:
            user_sessions[sender_id]["conversation_state"] = "product_info"
            return {
                "to": sender_id,
                "messages": [{
                    "type": "interactive",
                    "interactive": {
                        "type": "list",
                        "header": {"type": "text", "text": "Available Products"},
                        "body": {"text": "Select a product to learn more."},
                        "footer": {"text": "Tap an option below to continue."},
                        "action": {
                            "button": "Select Product",
                            "sections": [{
                                "title": "Products",
                                "rows": [
                                    {"id": "product_a", "title": "Model A - $299"},
                                    {"id": "product_b", "title": "Model B - $199"},
                                    {"id": "product_c", "title": "Model C - $99"}
                                ]
                            }]
                        }
                    }
                }]
            }

        elif message_text in ["menu_2", "2", "Customer Support"]:
            user_sessions[sender_id]["conversation_state"] = "support"
            return {"to": sender_id, "messages": [{"type": "text", "text": "Please describe your issue."}]}

        elif message_text in ["menu_3", "3", "Place Order"]:
            user_sessions[sender_id]["conversation_state"] = "order"
            return {
                "to": sender_id,
                "messages": [{
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": "Choose a product to order."},
                        "action": {
                            "buttons": [
                                {"type": "reply", "reply": {"id": "order_a", "title": "Model A"}},
                                {"type": "reply", "reply": {"id": "order_b", "title": "Model B"}},
                                {"type": "reply", "reply": {"id": "order_c", "title": "Model C"}}
                            ]
                        }
                    }
                }]
            }

    elif state == "product_info":
        products = {"product_a": "Model A - $299", "product_b": "Model B - $199", "product_c": "Model C - $99"}
        if message_text in products:
            user_sessions[sender_id]["context"]["product_interest"] = message_text
            user_sessions[sender_id]["conversation_state"] = "product_followup"
            return {
                "to": sender_id,
                "messages": [{
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": f"{products[message_text]}\nWould you like to place an order?"},
                        "action": {
                            "buttons": [
                                {"type": "reply", "reply": {"id": "yes_order", "title": "Yes"}},
                                {"type": "reply", "reply": {"id": "no", "title": "No"}}
                            ]
                        }
                    }
                }]
            }

    elif state == "support":
        user_sessions[sender_id]["context"]["support_issue"] = message_text
        user_sessions[sender_id]["conversation_state"] = "support_processing"
        return {
            "to": sender_id,
            "messages": [{
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": "Your issue has been recorded. Our support team will contact you shortly."},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": "menu", "title": "Back to Menu"}}
                        ]
                    }
                }
            }]
        }

    elif state == "order":
        user_sessions[sender_id]["context"]["order_product"] = message_text
        user_sessions[sender_id]["conversation_state"] = "order_quantity"
        return {"to": sender_id, "messages": [{"type": "text", "text": "Please enter the quantity."}]}

    elif state == "order_quantity":
        try:
            quantity = int(''.join(filter(str.isdigit, message_text)))
            if quantity > 0:
                user_sessions[sender_id]["context"]["order_quantity"] = quantity
                user_sessions[sender_id]["conversation_state"] = "order_confirmation"
                return {"to": sender_id, "messages": [{"type": "text", "text": "Please provide your delivery address."}]}
        except:
            return {"to": sender_id, "messages": [{"type": "text", "text": "Please enter a valid quantity."}]}

    elif state == "order_confirmation":
        user_sessions[sender_id]["context"]["delivery_address"] = message_text
        user_sessions[sender_id]["conversation_state"] = "order_complete"
        return {
            "to": sender_id,
            "messages": [{
                "type": "text",
                "text": "Thank you! Your order has been placed."
            }]
        }

    
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