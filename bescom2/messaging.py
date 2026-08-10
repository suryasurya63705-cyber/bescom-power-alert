import os
import logging
from twilio.rest import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_SMS_NUMBER  = os.environ.get("TWILIO_SMS_NUMBER", "")
TWILIO_WA_NUMBER   = "whatsapp:+14155238886"

def get_client():
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def send_whatsapp(to, body):
    try:
        logger.info(f"Sending WhatsApp to {to}")
        msg = get_client().messages.create(
            body=body,
            from_=TWILIO_WA_NUMBER,
            to=f"whatsapp:{to}"
        )
        logger.info(f"WhatsApp sent! SID: {msg.sid}")
        return {"success": True, "sid": msg.sid}
    except Exception as e:
        logger.error(f"WhatsApp ERROR to {to}: {str(e)}")
        return {"success": False, "error": str(e)}

def send_sms(to, body):
    # SMS requires a Twilio phone number (paid plan)
    # For free trial - only verified numbers can receive SMS
    if not TWILIO_SMS_NUMBER or TWILIO_SMS_NUMBER == "":
        logger.info("SMS number not configured, skipping SMS")
        return {"success": False, "error": "SMS number not configured"}
    try:
        logger.info(f"Sending SMS to {to}")
        msg = get_client().messages.create(
            body=body,
            from_=TWILIO_SMS_NUMBER,
            to=to
        )
        logger.info(f"SMS sent! SID: {msg.sid}")
        return {"success": True, "sid": msg.sid}
    except Exception as e:
        logger.error(f"SMS ERROR to {to}: {str(e)}")
        return {"success": False, "error": str(e)}

def notify_users(users, body):
    for user in users:
        logger.info(f"Notifying: {user.name} - {user.phone}")
        # Always try WhatsApp first
        wa_result = send_whatsapp(user.phone, body)
        # Also try SMS
        sms_result = send_sms(user.phone, body)
        logger.info(f"WhatsApp: {wa_result}, SMS: {sms_result}")
