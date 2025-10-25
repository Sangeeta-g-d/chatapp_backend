from firebase_admin import messaging

def send_fcm_notification(token, title, body, data=None):
    try:
        # Build payload data: always include title/body/click_action.
        payload_data = {
            "title": title,
            "body": body,
            "click_action": "FLUTTER_NOTIFICATION_CLICK"
        }

        # If caller provided extra data, selectively include fields.
        if data:
            # Include chat_group_id only when present (group message).
            chat_group_id = data.get("chat_group_id")
            if chat_group_id:
                payload_data["chat_group_id"] = chat_group_id

            # Include message_id when available.
            message_id = data.get("message_id")
            if message_id:
                payload_data["message_id"] = message_id

            # Include sender_id (useful for single chats and identification).
            sender_id = data.get("sender_id")
            if sender_id:
                payload_data["sender_id"] = sender_id

        # Create a notification payload for when app is in background/closed
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data=payload_data,
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