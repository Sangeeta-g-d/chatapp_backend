from urllib.parse import parse_qs
from rest_framework_simplejwt.tokens import UntypedToken
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
import jwt
from django.conf import settings

@database_sync_to_async
def get_user(validated_token):
    try:
        user_id = validated_token['user_id']
        return get_user_model().objects.get(id=user_id)
    except Exception:
        return AnonymousUser()

class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        try:
            query_string = scope["query_string"].decode()
            query_params = parse_qs(query_string)
            token = query_params.get("token", [None])[0]

            if token is None:
                scope["user"] = AnonymousUser()
                return await super().__call__(scope, receive, send)

            validated_token = UntypedToken(token)
            scope["user"] = await get_user(validated_token)
        except (InvalidToken, TokenError, jwt.exceptions.DecodeError):
            scope["user"] = AnonymousUser()
        except Exception:
            scope["user"] = AnonymousUser()

        close_old_connections()
        return await super().__call__(scope, receive, send)
