import os
import json
import requests
import logging
import uuid
from datetime import datetime, timedelta
from flask import Flask, request, jsonify # Removed session and flask_session as it wasn't used effectively and problematic on Vercel
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Removed Flask-Session configuration as in-memory dict was used and is unsuitable for Vercel.
# A persistent store (DB, Redis, Vercel KV) is needed for proper session management on Vercel.
# SECRET_KEY is still needed if you use other Flask extensions requiring it.
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "a_default_secret_key_for_dev")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://api.heltar.com/v1/messages/send"
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN")
# WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN") # Keep for implementing verification later

# CRITICAL: Replace this with a persistent store for production/Vercel
user_sessions = {}

# --- Payload Helper Functions ---

def create_text_payload(recipient_number, message_text):
    """Creates the payload for a simple text message."""
    return {
        "messages": [{
            "clientWaNumber": recipient_number,
            "message": message_text,
            "messageType": "text"
        }]
    }

def create_contact_payload(recipient_number, formatted_name, phone_wa_id, prefix=None):
    """Creates the payload for sending a contact card."""
    contact = {
        "name": {
            "formatted_name": formatted_name
        },
        "phones": [
            {
                "phone": phone_wa_id, # Often same as wa_id
                "wa_id": phone_wa_id
            }
        ]
    }
    # Add prefix if provided (as seen in Heltar example)
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
    """
    Creates the payload for an interactive message with buttons.
    buttons: List of dicts, e.g., [{'id': 'btn1', 'title': 'Button 1'}, ...]
    header_text: Optional text for the header.
    header_media: Optional dict for media header, e.g., {'type': 'image', 'link': 'http://...'}
                  Media types: 'image', 'video', 'document'
    """
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
    """
    Creates the payload for an interactive list message.
    sections: List of dicts, e.g., [{'title': 'Section 1', 'rows': [{'id': 'row1', 'title': 'Row 1', 'description': 'Desc 1'}, ...]}, ...]
    """
    # Ensure unique IDs across all rows if not already done
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
        if processed_rows: # Only add section if it has valid rows
             processed_sections.append({"title": section.get("title", ""), "rows": processed_rows})

    if not processed_sections:
        logger.error("Cannot create list payload with no valid sections/rows.")
        # Fallback to a text message or handle error appropriately
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
                    "button": button_text, # Text label for the button that opens the list
                    "sections": processed_sections
                }
            }
        }]
    }


# --- Refactored Send Function ---

def send_whatsapp_message(payload):
    """Sends a message payload using the Heltar API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }
    recipient = payload.get("messages", [{}])[0].get("clientWaNumber", "unknown") # For logging
    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        logger.info(f"Message sent to {recipient}. Status Code: {response.status_code}, Response: {response.text}")
        # Heltar might not return a useful body on success, status code is key
        return {"status": "success", "statusCode": response.status_code}
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending WhatsApp message to {recipient}: {str(e)}")
        # Log response body if available, might contain error details from Heltar
        if e.response is not None:
            logger.error(f"Heltar Response Body: {e.response.text}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error sending WhatsApp message to {recipient}: {str(e)}")
        return {"status": "error", "message": str(e)}


# --- Updated Core Logic ---

def process_message(sender_id, message_text=None, interactive_reply=None):
    """
    Processes incoming messages or interactive replies and determines the response type and data.

    Args:
        sender_id (str): The WhatsApp ID of the user.
        message_text (str, optional): The text of the user's message.
        interactive_reply (dict, optional): Parsed data from an interactive reply
                                            (e.g., {'type': 'button_reply', 'id': '...', 'title': '...'}).

    Returns:
        tuple: (response_type, data_dict)
               response_type (str): 'text', 'button', 'list', 'contact', or 'none'
               data_dict (dict): Data needed to build the response payload.
    """
    now = datetime.now()

    # --- Session Management (CRITICAL: Use persistent store here) ---
    if sender_id not in user_sessions:
        user_sessions[sender_id] = {
            "session_id": str(uuid.uuid4()),
            "created_at": now,
            "last_interaction": now,
            "conversation_state": "greeting",
            "context": {}
        }
        # Initial greeting
        return ("text", {"message_text": "Hello! Welcome to our service. How can I help you today?"})
    else:
         user_sessions[sender_id]["last_interaction"] = now

    session = user_sessions[sender_id]
    state = session["conversation_state"]
    context = session["context"]

    # Prioritize interactive replies for state transitions
    reply_id = interactive_reply.get('id') if interactive_reply else None
    reply_title = interactive_reply.get('title') if interactive_reply else None # Useful for context

    logger.info(f"Processing for {sender_id}: State='{state}', Text='{message_text}', ReplyID='{reply_id}'")

    # --- State Machine Logic ---

    if state == "greeting":
        session["conversation_state"] = "menu"
        # Use buttons for the menu
        menu_buttons = [
            {'id': 'menu_product_info', 'title': 'Product Information'},
            {'id': 'menu_support', 'title': 'Customer Support'},
            {'id': 'menu_order', 'title': 'Place an Order'},
            {'id': 'menu_contact', 'title': 'Send Contact Card'} # Example for contact msg
        ]
        return ("button", {
            "body_text": "I'm here to assist you. Please choose an option:",
            "buttons": menu_buttons
        })

    elif state == "menu":
        if reply_id == 'menu_product_info':
            session["conversation_state"] = "product_info_list" # Change state
             # Use a List for products
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
                "button_text": "View Products", # Button text to open the list
                "sections": product_sections
            })
        elif reply_id == 'menu_support':
            session["conversation_state"] = "support_request"
            return ("text", {"message_text": "Please describe the issue you're experiencing."})
        elif reply_id == 'menu_order':
            session["conversation_state"] = "order_start"
            # Maybe ask for product first using a list or buttons if products are known
            # For now, just ask for text input
            return ("text", {"message_text": "Which product would you like to order and the quantity? (e.g., 'Model A 2')"})
        elif reply_id == 'menu_contact':
             session["conversation_state"] = "contact_sent" # Or back to menu
             # Example: Send a predefined contact card
             return ("contact", {
                 "formatted_name": "Support Team",
                 "phone_wa_id": "15551234567", # Use a valid WA ID / number
                 "prefix": "Support" # Example optional field
             })
        else:
            # Re-show menu if invalid input or text message received
            menu_buttons = [
                {'id': 'menu_product_info', 'title': 'Product Information'},
                {'id': 'menu_support', 'title': 'Customer Support'},
                {'id': 'menu_order', 'title': 'Place an Order'},
                {'id': 'menu_contact', 'title': 'Send Contact Card'}
            ]
            return ("button", {
                "body_text": "Invalid selection. Please choose an option:",
                "buttons": menu_buttons
            })

    elif state == "product_info_list":
        # User selected a product from the list
        products = {"prod_A": "Model A - $299", "prod_B": "Model B - $199", "prod_C": "Model C - $99"}
        if reply_id in products:
            product_desc = products[reply_id]
            context["product_interest"] = reply_id # Store context (e.g., 'prod_A')
            context["product_interest_title"] = reply_title # Store title (e.g., 'Model A')
            session["conversation_state"] = "product_followup"
            # Ask followup question with buttons
            followup_buttons = [
                {'id': 'prod_order_yes', 'title': 'Place Order'},
                {'id': 'prod_order_no', 'title': 'Back to Menu'}
            ]
            return ("button", {
                "body_text": f"{product_desc}\n\nWould you like to place an order for {reply_title}?",
                "buttons": followup_buttons
                # Example: Add product image as header if available
                # "header_media": {"type": "image", "link": "http://example.com/images/model_a.png"}
            })
        else:
            # Invalid selection from list? Or maybe text? Re-prompt.
            session["conversation_state"] = "greeting" # Go back to start
            return ("text", {"message_text": "Sorry, I didn't understand that selection. Let's start over."})

    elif state == "product_followup":
         if reply_id == 'prod_order_yes':
             session["conversation_state"] = "order_quantity"
             # Use context for the product selected
             product_name = context.get("product_interest_title", "the selected product")
             return ("text", {"message_text": f"Great! How many units of {product_name} would you like?"})
         elif reply_id == 'prod_order_no':
             # Go back to the main menu
             session["conversation_state"] = "menu"
             menu_buttons = [
                {'id': 'menu_product_info', 'title': 'Product Information'},
                {'id': 'menu_support', 'title': 'Customer Support'},
                {'id': 'menu_order', 'title': 'Place an Order'},
                {'id': 'menu_contact', 'title': 'Send Contact Card'}
             ]
             return ("button", {
                "body_text": "Okay. How else can I help you?",
                "buttons": menu_buttons
            })
         else:
             # Invalid reply, re-ask
             followup_buttons = [
                {'id': 'prod_order_yes', 'title': 'Place Order'},
                {'id': 'prod_order_no', 'title': 'Back to Menu'}
             ]
             return ("button", {
                "body_text": "Please choose 'Place Order' or 'Back to Menu'.",
                "buttons": followup_buttons
            })

    elif state == "support_request":
        # User sent text describing the issue
        if message_text:
            context["support_issue"] = message_text
            session["conversation_state"] = "support_processing"
             # You could potentially send this to a ticketing system here
            return ("text", {"message_text": "Thank you. Our support team has received your request and will review the issue. We'll get back to you soon."})
        else:
             return ("text", {"message_text": "Please describe the issue you are facing."}) # Re-prompt if empty


    elif state == "order_start": # Asking for product/quantity text
        if message_text:
            # Basic parsing attempt (improve this significantly for production)
            parts = message_text.split()
            quantity = None
            product_name = None
            try:
                # Look for a number at the end
                if parts[-1].isdigit():
                    quantity = int(parts[-1])
                    product_name = " ".join(parts[:-1])
                else: # Assume quantity might be 1 if only product name given? Or just ask again.
                     product_name = message_text
            except:
                pass # Failed parsing

            if quantity and quantity > 0 and product_name:
                 context["order_product"] = product_name # Store raw text for now
                 context["order_quantity"] = quantity
                 session["conversation_state"] = "order_address"
                 return ("text", {"message_text": f"Okay, {quantity} of {product_name}. Please provide your delivery address."})
            else:
                 # Ask again more clearly
                 return ("text", {"message_text": "Sorry, I couldn't understand that. Please provide the product name and quantity (e.g., 'Model B 3')."})
        else:
             return ("text", {"message_text": "Please tell me the product and quantity you want to order."})


    elif state == "order_quantity": # Asking specifically for quantity after product selected
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
             # Here you would typically save the order to a database
            product = context.get("product_interest_title") or context.get("order_product", "Unknown Product")
            quantity = context.get("order_quantity", "N/A")
            address = context.get("delivery_address", "N/A")
            logger.info(f"Order Placed: User={sender_id}, Product={product}, Qty={quantity}, Address={address}")
            # Clear context for next order (optional)
            context.pop("order_product", None)
            context.pop("order_quantity", None)
            context.pop("delivery_address", None)
            context.pop("product_interest", None)
            context.pop("product_interest_title", None)

            # Send confirmation and loop back to menu
            session["conversation_state"] = "menu" # Or a "thank_you_menu" state
            menu_buttons = [
                {'id': 'menu_product_info', 'title': 'Product Information'},
                {'id': 'menu_support', 'title': 'Customer Support'},
                {'id': 'menu_order', 'title': 'Place an Order'},
                {'id': 'menu_contact', 'title': 'Send Contact Card'}
             ]
            return ("button", {
                 "header_text": "Order Confirmed!",
                 "body_text": f"Thank you! Your order for {quantity} x {product} has been placed.\n\nIs there anything else?",
                 "buttons": menu_buttons
             })
        else:
             return ("text", {"message_text": "Please provide the delivery address."})

    # --- Fallback ---
    # If state is something unexpected or finished
    logger.warning(f"Unhandled state '{state}' or situation for user {sender_id}. Resetting.")
    session["conversation_state"] = "greeting" # Reset state
    # You might want a different fallback message
    return ("text", {"message_text": "Sorry, something went wrong. Let's start over. How can I help?"})


# --- Webhook Endpoint ---

@app.route('/')
def home():
    return jsonify({"message": "WhatsApp Flask Server with Heltar Integration is Running!"})

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'POST':
        # --- Add Signature Verification (Highly Recommended!) ---
        # signature = request.headers.get('X-Hub-Signature-256') # Check Heltar docs for header name
        # if not verify_signature(request.data, signature): # Implement verify_signature function
        #     logger.warning("Invalid webhook signature received.")
        #     return jsonify({"status": "error", "message": "Invalid signature"}), 403
        # logger.info("Webhook signature verified.")
        # ---

        try:
            data = request.json
            logger.info(f"Received webhook data: {json.dumps(data, indent=2)}")

            # Process messages (adapt based on actual Heltar payload structure)
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
                                    continue # Skip message if no sender

                                if message_type == 'text':
                                    message_text = message.get('text', {}).get('body')
                                elif message_type == 'interactive':
                                    interactive = message.get('interactive', {})
                                    interaction_type = interactive.get('type') # 'button_reply' or 'list_reply'
                                    if interaction_type in ['button_reply', 'list_reply']:
                                        interactive_reply = interactive.get(interaction_type) # Contains 'id', 'title', etc.
                                        # Log the interaction clearly
                                        logger.info(f"Interactive reply from {sender_id}: Type='{interaction_type}', ID='{interactive_reply.get('id')}', Title='{interactive_reply.get('title')}'")
                                    else:
                                        logger.warning(f"Received unknown interactive type: {interaction_type}")
                                        continue # Skip if we don't know how to handle
                                else:
                                    # Handle other message types if needed (image, audio, location etc.)
                                    logger.info(f"Received non-text/interactive message type '{message_type}' from {sender_id}. Sending default response.")
                                    # Optionally send a default "I can only process text/buttons" message
                                    message_text = None # Ensure we don't process it as standard text below
                                    # Let process_message decide fallback based on state, or send fixed response here:
                                    payload = create_text_payload(sender_id, "Sorry, I can currently only understand text messages and interactive replies.")
                                    send_whatsapp_message(payload)
                                    continue


                                # Ensure we have either text or an interactive reply to process
                                if message_text or interactive_reply:
                                    # Get the response type and data from the state machine
                                    response_type, response_data = process_message(sender_id, message_text, interactive_reply)

                                    # Build the payload based on the response type
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
                                        pass # Do nothing
                                    else:
                                         logger.error(f"Unknown response type '{response_type}' from process_message.")
                                         # Fallback to a generic error message
                                         payload = create_text_payload(sender_id, "Sorry, an internal error occurred.")


                                    # Send the response if a payload was generated
                                    if payload:
                                        send_whatsapp_message(payload)
                                else:
                                    # If it wasn't text or a handled interactive reply, maybe reiterate options?
                                    # This depends on the desired bot behavior for unsupported input.
                                    # Consider getting the current state and re-sending the last prompt.
                                    logger.info(f"No actionable input (text/interactive) from {sender_id}. Current state: {user_sessions.get(sender_id, {}).get('conversation_state')}")
                                    # Example: Resend last prompt based on state (needs more logic)
                                    # Or just send a generic help message

            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"Error processing webhook POST request: {str(e)}", exc_info=True) # Log traceback
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    # Remember: len(user_sessions) is NOT reliable on Vercel due to statelessness.
    # You'd need to query your persistent store for active session count.
    return jsonify({
        "status": "active",
        "active_sessions_in_memory": len(user_sessions), # This count is only for the current instance
        "warning": "Session count is instance-specific and not accurate for overall active users on serverless.",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    # Set debug=True for local development ONLY, False for Vercel/production
    app.run(host='0.0.0.0', port=port, debug=False)