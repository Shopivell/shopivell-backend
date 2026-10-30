"""Verify handoffs reach connected screens without restoring lead alerts."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.whatsapp.crm_service import CRMService, NotificationType


async def main():
    crm = CRMService(uuid4(), Mock())
    notification = SimpleNamespace(id=uuid4())
    crm.notification_service = SimpleNamespace(
        create_notification=AsyncMock(return_value=notification),
        get_unread_count=Mock(return_value={"unread_count": 1}),
    )
    crm.create_handoff_task = Mock()
    conversation = SimpleNamespace(id=uuid4(), phone_number="263771234567")
    with patch("modules.whatsapp.crm_service.notification_manager.send_notification", new_callable=AsyncMock) as send:
        await crm.notify_handoff(conversation, "Pharmacist needed", query_text="Question")
        send.assert_awaited_once_with(store_id=str(crm.store_id), notification=notification, unread_count=1)
        assert crm.notification_service.create_notification.call_args.kwargs["notification_type"] == NotificationType.HANDOFF
        crm.create_handoff_task.assert_called_once()

        # Disconnected clients must not prevent the persisted handoff task.
        send.side_effect = RuntimeError("Disconnected")
        crm.create_handoff_task.reset_mock()
        await crm.notify_handoff(conversation, "Pharmacist needed")
        crm.create_handoff_task.assert_called_once()

        send.reset_mock()
        crm.notification_service.create_notification.reset_mock()
        await crm.notify_handoff(conversation, "Disabled", config=SimpleNamespace(notify_on_handoff=False))
        send.assert_not_awaited()
        crm.notification_service.create_notification.assert_not_awaited()
    print("PASS: handoffs broadcast immediately, respect preferences, and survive disconnection")


asyncio.run(main())
