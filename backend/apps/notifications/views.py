"""通知接口。全部只作用于当前登录者，永远按 recipient 过滤。"""

from __future__ import annotations

from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications import events
from apps.notifications.models import Notification
from apps.notifications.serializers import (
    EmailPreferenceSerializer,
    MarkReadInputSerializer,
    NotificationSerializer,
)
from apps.notifications.services import get_email_preference, mark_read, unread_count
from common.permissions import IsAuthenticatedAndActive


class NotificationListView(ListAPIView):
    """GET /api/v1/notifications/ —— 只列当前用户自己的通知（?unread=1&event=）。

    `?event=` 只认 `events.EVENT_LABELS` 里的键；认不出的值静默忽略（不报错、不筛），
    与各列表接口的筛选参数同口径。
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticatedAndActive]

    def get_queryset(self):
        queryset = Notification.objects.filter(recipient=self.request.user).select_related(
            "actor", "target_content_type"
        )
        if self.request.query_params.get("unread") == "1":
            queryset = queryset.filter(read_at__isnull=True)
        event = self.request.query_params.get("event", "").strip()
        if event in events.EVENT_LABELS:
            queryset = queryset.filter(event=event)
        return queryset


class UnreadCountView(APIView):
    """GET /api/v1/notifications/unread-count/"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        return Response({"unread": unread_count(request.user)})


class MarkReadView(APIView):
    """POST /api/v1/notifications/read/ —— body 里给 ids 则标指定几条，不给则全部。"""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request) -> Response:
        serializer = MarkReadInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data.get("ids")
        updated = mark_read(request.user, ids if ids else None)
        return Response({"updated": updated, "unread": unread_count(request.user)})


class EmailPreferenceView(APIView):
    """GET/PATCH /api/v1/notifications/preference/ —— 邮件提醒偏好，默认关。"""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        preference = get_email_preference(request.user)
        data = EmailPreferenceSerializer(preference).data
        data["available_events"] = [
            {"event": key, "label": label} for key, label in events.EVENT_LABELS.items()
        ]
        return Response(data)

    def patch(self, request: Request) -> Response:
        preference = get_email_preference(request.user)
        serializer = EmailPreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
