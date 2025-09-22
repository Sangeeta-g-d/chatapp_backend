from firebase_admin import messaging

def send_fcm_notification(token, title, body, data=None):
    try:
        message = messaging.Message(
            token=token,
            data={
                "title": title,
                "body": body,
                **(data or {})   # merge extra data
            }
        )
        response = messaging.send(message)
        print(f"[FCM] Sent notification: {response}")
    except Exception as e:
        print(f"[Error] Sending FCM failed: {e}")