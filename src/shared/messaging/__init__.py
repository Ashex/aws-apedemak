"""
This module provides a platform-agnostic messaging interface (port) with 
concrete implementations (adapters) for various messaging platforms.
"""

from .interface import (
    MessagingInterface,
    AccessRequestPayload,
    ApprovalMessagePayload,
    MessageUpdatePayload,
    WebhookEvent,
    WebhookEventType,
    WebhookResponse
)
from .slack_adapter import SlackMessagingAdapter

__all__ = [
    'MessagingInterface',
    'AccessRequestPayload',
    'ApprovalMessagePayload',
    'MessageUpdatePayload',
    'WebhookEvent',
    'WebhookEventType',
    'WebhookResponse',
    'SlackMessagingAdapter'
]
