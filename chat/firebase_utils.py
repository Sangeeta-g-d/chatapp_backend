from firebase_admin import messaging

def send_fcm_notification(token, title, body, data=None):
    try:
        # Create a notification payload for when app is in background/closed
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data={
                "title": title,
                "body": body,
                "chat_group_id": data.get("chat_group_id", ""),
                "message_id": data.get("message_id", ""),
                "sender_id": data.get("sender_id", ""),
                "click_action": "FLUTTER_NOTIFICATION_CLICK"  # Important for Flutter
            } if data else {
                "title": title,
                "body": body,
                "click_action": "FLUTTER_NOTIFICATION_CLICK"
            },
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='high_importance_channel',  # Match your Flutter channel
                    sound='default'
                )
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default',
                        badge=1,
                        content_available=True  # Important for iOS background
                    )
                )
            )
        )
        response = messaging.send(message)
        print(f"[FCM] Sent notification: {response}")
    except Exception as e:
        print(f"[Error] Sending FCM failed: {e}")