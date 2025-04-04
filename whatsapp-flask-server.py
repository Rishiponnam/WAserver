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

def send_whatsapp_message(recipient_number, message, message_type="text"):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }

    if message_type == "text":
        payload = {
            "messages": [{
                "clientWaNumber": recipient_number,
                "message": message,
                "messageType": "text"
            }]
        }
    elif message_type == "buttons":
        payload = {
            "messages": [{
                "clientWaNumber": recipient_number,
                "messageType": "interactiveButtons",
                "interactiveButtons": {
                    "title": message,
                    "buttons": [
                        {"id": "1", "title": "1"},
                        {"id": "2", "title": "2"},
                        {"id": "3", "title": "3"},
                        {"id": "4", "title": "4"},
                        {"id": "5", "title": "5"}
                    ]
                }
            }]
        }
    elif message_type == "image":
        payload = {
            "messages": [{
                "clientWaNumber": recipient_number,
                "messageType": "image",
                "image": {
                    "url": "https://www.google.co.in/imgres?q=random%20photos&imgurl=https%3A%2F%2Fcdn.pixabay.com%2Fphoto%2F2016%2F07%2F07%2F16%2F46%2Fdice-1502706_640.jpg&imgrefurl=https%3A%2F%2Fpixabay.com%2Fimages%2Fsearch%2Frandom%2F&docid=RaG63Wpx0MhExM&tbnid=RX3IsDRqbm7WyM&vet=12ahUKEwjf4NvQ0L2MAxUGd_UHHQYlM7UQM3oECEgQAA..i&w=640&h=427&hcb=2&ved=2ahUKEwjf4NvQ0L2MAxUGd_UHHQYlM7UQM3oECEgQAA"
                }
            }]
        }
    elif message_type == "image2":
        payload = {
            "messages": [{
                "clientWaNumber": recipient_number,
                "messageType": "image",
                "image": {
                    "url": "https://www.google.co.in/imgres?q=random%20photos%20of%20things&imgurl=https%3A%2F%2Fimages.pexels.com%2Fphotos%2F9304725%2Fpexels-photo-9304725.jpeg%3Fcs%3Dsrgb%26dl%3Dpexels-jj-jordan-44924743-9304725.jpg%26fm%3Djpg&imgrefurl=https%3A%2F%2Fwww.pexels.com%2Fsearch%2Frandom%2520objects%2F&docid=fWWQgzUAPejkDM&tbnid=c25_s8kVWDGc-M&vet=12ahUKEwja1PzA1r2MAxWfh68BHW45BIMQM3oECGsQAA..i&w=3681&h=4601&hcb=2&ved=2ahUKEwja1PzA1r2MAxWfh68BHW45BIMQM3oECGsQAA"
                }
            }]
        }
    elif message_type == "location":
        payload = {
            "messages": [{
                "clientWaNumber": recipient_number,
                "messageType": "location",
                "location": {
                    "latitude": 37.7749,
                    "longitude": -122.4194,
                    "name": "San Francisco",
                    "address": "California, USA"
                }
            }]
        }
    elif message_type == "contact":
        payload = {
            "messages": [{
                "clientWaNumber": recipient_number,
                "messageType": "contact",
                "contact": {
                    "name": {
                        "formattedName": "John Doe",
                        "firstName": "John",
                        "lastName": "Doe"
                    },
                    "phones": [{
                        "phone": "+1234567890",
                        "type": "MOBILE"
                    }]
                }
            }]
        }
    else:
        return None

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