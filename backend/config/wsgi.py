"""WSGI 入口。生产用 `DJANGO_SETTINGS_MODULE=config.settings.prod`。"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

application = get_wsgi_application()
