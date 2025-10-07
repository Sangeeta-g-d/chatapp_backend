# utils.py
import random
from django.core.mail import send_mail
from django.conf import settings
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)
def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_via_email(email, otp):
    subject = 'Your OTP Code'
    message = f'Your OTP is {otp}. It is valid for 10 minutes.'
    from_email = settings.DEFAULT_FROM_EMAIL
    send_mail(subject, message, from_email, [email])


def send_otp(phone_number, otp):
    """
    Send OTP using Taqnyat SMS API.
    """
    logger.debug(f"Raw phone number: {phone_number}")
    phone_number = phone_number.lstrip('+').replace(" ", "")
    logger.debug(f"Processed phone number: {phone_number}")

    message_body = (
        f"HALA WALLA!!\n"
        f"Your Verification code: {otp}, Never share this code with anyone.\n"
        f"gulfwest.com\n\n"
        f"هلا و الله !!!\n"
        f"رمز التأكيد الخاص بك {otp}, لا تشارك هذا الرمز مع أحد\n"
        f"شركة الخليج الغربية"
    )

    payload = {
        "body": message_body,
        "recipients": [phone_number],
        "sender": settings.TAQNYAT_SENDER_NAME
    }

    headers = {
        "Authorization": f"Bearer {settings.TAQNYAT_API_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(settings.TAQNYAT_API_URL, json=payload, headers=headers)
        logger.debug(f"Taqnyat response: {response.status_code} - {response.text}")

        if response.status_code not in [200, 201]:
            raise Exception(f"Taqnyat SMS failed: {response.text}")

        logger.info(f"OTP sent successfully to {phone_number}")
        return response.json()

    except Exception as e:
        logger.exception(f"Error sending OTP to {phone_number}: {e}")
        raise
