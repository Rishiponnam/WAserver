import os
import json
import requests
import logging
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "a_default_secret_key_for_dev")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://api.heltar.com/v1/messages/send"
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN")

# !! Replace this with Redis client !!
user_sessions = {} # This will be replaced by Redis interaction

def create_text_payload(recipient_number, message_text):
    return {
        "messages": [{
            "clientWaNumber": recipient_number,
            "message": message_text,
            "messageType": "text"
        }]
    }

def create_contact_payload(recipient_number, formatted_name, phone_wa_id, prefix=None):
    contact = {
        "name": {
            "formatted_name": formatted_name
        },
        "phones": [
            {
                "phone": phone_wa_id,
                "wa_id": phone_wa_id
            }
        ]
    }
    if prefix:
        contact["name"]["prefix"] = prefix

    return {
        "messages": [{
            "clientWaNumber": recipient_number,
            "messageType": "contacts",
            "contacts": [contact]
        }]
    }

def create_button_payload(recipient_number, body_text, buttons, header_text=None, header_media=None):
    interactive = {
        "type": "button",
        "body": {
            "text": body_text
        },
        "action": {
            "buttons": [{"type": "reply", "reply": btn} for btn in buttons]
        }
    }
    if header_text:
         interactive["header"] = {"type": "text", "text": header_text}
    elif header_media:
        media_type = header_media.get('type')
        link = header_media.get('link')
        if media_type in ['image', 'video', 'document'] and link:
             interactive["header"] = {
                 "type": media_type,
                 media_type: {"link": link}
             }
        else:
            logger.warning(f"Invalid header_media format: {header_media}")

    return {
         "messages": [{
             "clientWaNumber": recipient_number,
             "messageType": "interactive",
             "interactive": interactive
         }]
    }

def create_list_payload(recipient_number, header_text, body_text, button_text, sections):
    all_row_ids = set()
    processed_sections = []
    for section in sections:
        processed_rows = []
        for row in section.get("rows", []):
            if row.get("id") in all_row_ids:
                logger.warning(f"Duplicate row ID found and skipped: {row.get('id')}")
                continue
            all_row_ids.add(row.get("id"))
            processed_rows.append(row)
        if processed_rows:
             processed_sections.append({"title": section.get("title", ""), "rows": processed_rows})

    if not processed_sections:
        logger.error("Cannot create list payload with no valid sections/rows.")
        return create_text_payload(recipient_number, "Sorry, there was an error preparing the list.")


    return {
        "messages": [{
            "clientWaNumber": recipient_number,
            "messageType": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": header_text
                },
                "body": {
                    "text": body_text
                },
                "action": {
                    "button": button_text,
                    "sections": processed_sections
                }
            }
        }]
    }

def send_whatsapp_message(payload):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }
    recipient = payload.get("messages", [{}])[0].get("clientWaNumber", "unknown")
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        logger.info(f"Message sent to {recipient}. Status Code: {response.status_code}, Response: {response.text}")
        return {"status": "success", "statusCode": response.status_code}
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending WhatsApp message to {recipient}: {str(e)}")
        if e.response is not None:
            logger.error(f"Heltar Response Body: {e.response.text}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error sending WhatsApp message to {recipient}: {str(e)}")
        return {"status": "error", "message": str(e)}

def process_message(sender_id, message_text=None, interactive_reply=None):
    now = datetime.now()

    # !! Replace user_sessions interaction with Redis below !!
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {
            "session_id": str(uuid.uuid4()),
            "created_at": now.isoformat(), # Use ISO format for JSON compatibility
            "last_interaction": now.isoformat(),
            "conversation_state": "greeting",
            "context": {}
        }
        return ("text", {"message_text": "Hello! Welcome to our service. How can I help you today?"})
    else:
         user_sessions[sender_id]["last_interaction"] = now.isoformat()

    session = user_sessions[sender_id]
    state = session["conversation_state"]
    context = session["context"]

    reply_id = interactive_reply.get('id') if interactive_reply else None
    reply_title = interactive_reply.get('title') if interactive_reply else None

    logger.info(f"Processing for {sender_id}: State='{state}', Text='{message_text}', ReplyID='{reply_id}'")

    if state == "greeting":
        session["conversation_state"] = "menu"
        menu_buttons = [
            {'id': 'menu_product_info', 'title': 'Product Information'},
            {'id': 'menu_support', 'title': 'Customer Support'},
            {'id': 'menu_order', 'title': 'Place an Order'}
            # 4th button removed
        ]
        return ("button", {
            "body_text": "I'm here to assist you. Please choose an option:",
            "buttons": menu_buttons
        })

    elif state == "menu":
        if reply_id == 'menu_product_info':
            session["conversation_state"] = "product_info_list"
            product_sections = [{
                 "title": "Our Products",
                 "rows": [
                     {'id': 'prod_A', 'title': 'Model A', 'description': 'High-end model - $299'},
                     {'id': 'prod_B', 'title': 'Model B', 'description': 'Mid-range model - $199'},
                     {'id': 'prod_C', 'title': 'Model C', 'description': 'Budget model - $99'}
                 ]
            }]
            return ("list", {
                "header_text": "Product Catalog",
                "body_text": "Select a product to learn more.",
                "button_text": "View Products",
                "sections": product_sections
            })
        elif reply_id == 'menu_support':
            session["conversation_state"] = "support_request"
            return ("text", {"message_text": "Please describe the issue you're experiencing."})
        elif reply_id == 'menu_order':
            session["conversation_state"] = "order_start"
            return ("text", {"message_text": "Which product would you like to order and the quantity? (e.g., 'Model A 2')"})
        # Removed contact option handling
        else:
            menu_buttons = [
                {'id': 'menu_product_info', 'title': 'Product Information'},
                {'id': 'menu_support', 'title': 'Customer Support'},
                {'id': 'menu_order', 'title': 'Place an Order'}
            ]
            return ("button", {
                "body_text": "Invalid selection. Please choose an option:",
                "buttons": menu_buttons
            })

    elif state == "product_info_list":
        products = {"prod_A": "Model A - $299", "prod_B": "Model B - $199", "prod_C": "Model C - $99"}
        if reply_id in products:
            product_desc = products[reply_id]
            context["product_interest"] = reply_id
            context["product_interest_title"] = reply_title
            session["conversation_state"] = "product_followup"
            followup_buttons = [
                {'id': 'prod_order_yes', 'title': 'Place Order'},
                {'id': 'prod_order_no', 'title': 'Back to Menu'}
            ]
            return ("button", {
                "body_text": f"{product_desc}\n\nWould you like to place an order for {reply_title}?",
                "buttons": followup_buttons
            })
        else:
            session["conversation_state"] = "greeting"
            return ("text", {"message_text": "Sorry, I didn't understand that selection. Let's start over."})

    elif state == "product_followup":
         if reply_id == 'prod_order_yes':
             session["conversation_state"] = "order_quantity"
             product_name = context.get("product_interest_title", "the selected product")
             return ("text", {"message_text": f"Great! How many units of {product_name} would you like?"})
         elif reply_id == 'prod_order_no':
             session["conversation_state"] = "menu"
             menu_buttons = [
                 {'id': 'menu_product_info', 'title': 'Product Information'},
                 {'id': 'menu_support', 'title': 'Customer Support'},
                 {'id': 'menu_order', 'title': 'Place an Order'}
             ]
             return ("button", {
                "body_text": "Okay. How else can I help you?",
                "buttons": menu_buttons
            })
         else:
             followup_buttons = [
                {'id': 'prod_order_yes', 'title': 'Place Order'},
                {'id': 'prod_order_no', 'title': 'Back to Menu'}
             ]
             return ("button", {
                "body_text": "Please choose 'Place Order' or 'Back to Menu'.",
                "buttons": followup_buttons
            })

    elif state == "support_request":
        if message_text:
            context["support_issue"] = message_text
            session["conversation_state"] = "support_processing"
            return ("text", {"message_text": "Thank you. Our support team has received your request and will review the issue. We'll get back to you soon."})
        else:
             return ("text", {"message_text": "Please describe the issue you are facing."})

    elif state == "order_start":
        if message_text:
            parts = message_text.split()
            quantity = None
            product_name = None
            try:
                if parts[-1].isdigit():
                    quantity = int(parts[-1])
                    product_name = " ".join(parts[:-1])
                else:
                     product_name = message_text
            except:
                pass

            if quantity and quantity > 0 and product_name:
                 context["order_product"] = product_name
                 context["order_quantity"] = quantity
                 session["conversation_state"] = "order_address"
                 return ("text", {"message_text": f"Okay, {quantity} of {product_name}. Please provide your delivery address."})
            else:
                 return ("text", {"message_text": "Sorry, I couldn't understand that. Please provide the product name and quantity (e.g., 'Model B 3')."})
        else:
             return ("text", {"message_text": "Please tell me the product and quantity you want to order."})


    elif state == "order_quantity":
         if message_text and message_text.isdigit() and int(message_text) > 0:
             context["order_quantity"] = int(message_text)
             session["conversation_state"] = "order_address"
             product_name = context.get("product_interest_title", "the selected product")
             return ("text", {"message_text": f"Okay, {context['order_quantity']} of {product_name}. Please provide your delivery address."})
         else:
             return ("text", {"message_text": "Please enter a valid number for the quantity."})

    elif state == "order_address":
        if message_text:
            context["delivery_address"] = message_text
            session["conversation_state"] = "order_complete"
            product = context.get("product_interest_title") or context.get("order_product", "Unknown Product")
            quantity = context.get("order_quantity", "N/A")
            address = context.get("delivery_address", "N/A")
            logger.info(f"Order Placed: User={sender_id}, Product={product}, Qty={quantity}, Address={address}")

            context.pop("order_product", None)
            context.pop("order_quantity", None)
            context.pop("delivery_address", None)
            context.pop("product_interest", None)
            context.pop("product_interest_title", None)

            session["conversation_state"] = "menu"
            menu_buttons = [
                 {'id': 'menu_product_info', 'title': 'Product Information'},
                 {'id': 'menu_support', 'title': 'Customer Support'},
                 {'id': 'menu_order', 'title': 'Place an Order'}
             ]
            return ("button", {
                 "header_text": "Order Confirmed!",
                 "body_text": f"Thank you! Your order for {quantity} x {product} has been placed.\n\nIs there anything else?",
                 "buttons": menu_buttons
             })
        else:
             return ("text", {"message_text": "Please provide the delivery address."})

    # !! This final part of process_message needs to save the session back to Redis !!
    # For now, it just returns the fallback for the in-memory version
    logger.warning(f"Unhandled state '{state}' or situation for user {sender_id}. Resetting.")
    session["conversation_state"] = "greeting"
    return ("text", {"message_text": "Sorry, something went wrong. Let's start over. How can I help?"})


@app.route('/')
def home():
    return jsonify({"message": "WhatsApp Flask Server with Heltar Integration is Running!"})

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        try:
            data = request.json
            logger.info(f"Received webhook data: {json.dumps(data, indent=2)}")

            if 'entry' in data:
                for entry in data.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        if 'messages' in value:
                            for message in value.get('messages', []):
                                sender_id = message.get('from')
                                message_type = message.get('type')
                                message_text = None
                                interactive_reply = None

                                if not sender_id:
                                    logger.warning("Message received without sender ID.")
                                    continue

                                if message_type == 'text':
                                    message_text = message.get('text', {}).get('body')
                                elif message_type == 'interactive':
                                    interactive = message.get('interactive', {})
                                    interaction_type = interactive.get('type')
                                    if interaction_type in ['button_reply', 'list_reply']:
                                        interactive_reply = interactive.get(interaction_type)
                                        logger.info(f"Interactive reply from {sender_id}: Type='{interaction_type}', ID='{interactive_reply.get('id')}', Title='{interactive_reply.get('title')}'")
                                    else:
                                        logger.warning(f"Received unknown interactive type: {interaction_type}")
                                        continue
                                else:
                                    logger.info(f"Received non-text/interactive message type '{message_type}' from {sender_id}. Ignoring.")
                                    # Optionally send a message saying you only understand text/buttons
                                    # payload = create_text_payload(sender_id, "Sorry, I can currently only understand text messages and interactive replies.")
                                    # send_whatsapp_message(payload)
                                    continue


                                if message_text or interactive_reply:
                                    # !! process_message will need changes for Redis !!
                                    response_type, response_data = process_message(sender_id, message_text, interactive_reply)

                                    payload = None
                                    if response_type == 'text':
                                        payload = create_text_payload(sender_id, response_data['message_text'])
                                    elif response_type == 'button':
                                        payload = create_button_payload(sender_id,
                                                                        response_data['body_text'],
                                                                        response_data['buttons'],
                                                                        response_data.get('header_text'),
                                                                        response_data.get('header_media'))
                                    elif response_type == 'list':
                                         payload = create_list_payload(sender_id,
                                                                         response_data['header_text'],
                                                                         response_data['body_text'],
                                                                         response_data['button_text'],
                                                                         response_data['sections'])
                                    elif response_type == 'contact':
                                         payload = create_contact_payload(sender_id,
                                                                          response_data['formatted_name'],
                                                                          response_data['phone_wa_id'],
                                                                          response_data.get('prefix'))
                                    elif response_type == 'none':
                                        logger.info(f"No response generated for user {sender_id}")
                                        pass
                                    else:
                                         logger.error(f"Unknown response type '{response_type}' from process_message.")
                                         payload = create_text_payload(sender_id, "Sorry, an internal error occurred.")

                                    if payload:
                                        send_whatsapp_message(payload)
                                else:
                                     logger.info(f"No actionable input (text/interactive) from {sender_id}.")


            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"Error processing webhook POST request: {str(e)}", exc_info=True)
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    # This route would need to query Redis for active sessions if that metric is needed
    return jsonify({
        "status": "active",
        "warning": "Session count requires Redis query for accuracy on serverless.",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)