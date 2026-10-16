"""ASGI 入口。当前未用 WebSocket，保留以便日后接入。"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

application = get_asgi_application()
