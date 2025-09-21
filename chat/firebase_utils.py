from firebase_admin import messaging

def send_fcm_notification(token, title, body, data=None):
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            token=token,
            data=data or {}
        )
        response = messaging.send(message)
        print(f"[FCM] Sent notification: {response}")
    except Exception as e:
        print(f"[Error] Sending FCM failed: {e}")
