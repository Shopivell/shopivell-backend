"""Require authentication for staff-facing WhatsApp HTTP endpoints."""
import re

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from utils.jwt_auth import get_current_user


class WhatsAppAccessMiddleware(BaseHTTPMiddleware):
    _public = frozenset({
        '/v1/api/whatsapp/webhook', '/v1/api/whatsapp/flow-endpoint',
        '/v1/api/whatsapp/connect/callback', '/v1/api/whatsapp/connect/info',
        '/v1/api/whatsapp/paynow-callback',
    })
    _staff_patterns = (
        r'/v1/api/whatsapp/store/[^/]+/(?:accounts|unread-count)',
        r'/v1/api/whatsapp/accounts/[^/]+/(?:messages|conversations|leads|send-text|send-attachment|send-bulk)(?:/.*)?',
        r'/v1/api/whatsapp/stores/[^/]+/saved-replies(?:/[^/]+)?',
        r'/v1/api/whatsapp/conversations/[^/]+/mark-read',
        r'/v1/api/whatsapp/messages/[^/]+/mark-read',
        r'/v1/api/whatsapp/connect/accounts',
        r'/v1/api/whatsapp/leads(?:/analytics)?',
        r'/v1/api/whatsapp/ask',
    )

    async def dispatch(self, request, call_next):
        path = request.url.path.rstrip('/')
        if not path.startswith('/v1/api/whatsapp/') or path in self._public or request.method == 'OPTIONS':
            return await call_next(request)
        authorization = request.headers.get('authorization', '')
        scheme, _, token = authorization.partition(' ')
        if scheme.lower() != 'bearer' or not token:
            return JSONResponse({'detail': 'Not authenticated'}, status_code=401)
        try:
            user = await get_current_user(HTTPAuthorizationCredentials(scheme='Bearer', credentials=token))
        except HTTPException as exc:
            return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        if user.role.lower() == 'staff' and not any(re.fullmatch(pattern, path) for pattern in self._staff_patterns):
            return JSONResponse({'detail': 'This action is not available to staff'}, status_code=403)
        return await call_next(request)
