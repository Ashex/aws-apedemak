"""
Messaging Platform Interface

Defines the contract for messaging platform adapters so we can add additional platforms later.
This is all based on Slack so we might need to re-work things when adding new platforms.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


class WebhookEventType(Enum):
    """Types of webhook events"""
    URL_VERIFICATION = "url_verification"
    MESSAGE_SHORTCUT = "message_shortcut"
    VIEW_SUBMISSION = "view_submission"
    BUTTON_ACTION = "button_action"
    UNKNOWN = "unknown"


@dataclass
class WebhookEvent:
    """Platform-agnostic webhook event"""
    event_type: WebhookEventType
    raw_payload: Dict[str, Any]
    user_id: str
    user_email: Optional[str] = None
    trigger_id: Optional[str] = None  # For opening modals
    view_data: Optional[Dict[str, Any]] = None  # Modal submission data
    action_data: Optional[Dict[str, Any]] = None  # Button action data
    metadata: Optional[Dict[str, Any]] = None  # Additional context


@dataclass
class WebhookResponse:
    """Platform-agnostic webhook response"""
    status_code: int
    body: Dict[str, Any]
    headers: Optional[Dict[str, str]] = None


@dataclass
class AccessRequestPayload:
    """Data for creating access request modal"""
    accounts: List[Dict[str, str]]  # [{'id': '...', 'name': '...'}]
    permission_durations: List[int]  # Duration options in seconds
    message_context: Optional[Dict[str, str]] = None  # Context from triggering message


@dataclass
class ApprovalMessagePayload:
    """Data for posting approval request message"""
    channel_id: str
    requester_id: str
    requester_email: str
    account_id: str
    account_name: str
    permission_set: str
    duration_seconds: int
    justification: str
    approver_emails: List[str]
    dry_run: bool = False


@dataclass
class MessageUpdatePayload:
    """Data for updating a message"""
    channel_id: str
    message_id: str
    account_name: str
    permission_set: str
    duration_seconds: int
    actor_id: str  # User who approved/denied
    approved: bool
    dry_run: bool = False


class MessagingInterface(ABC):
    """
    Abstract for messaging platform interactions
    
    This interface defines the contract that all messaging platform adapters
    must implement, allowing the application to work with any messaging platform
    without coupling to specific implementations.
    """
    
    @abstractmethod
    def verify_webhook_signature(
        self,
        body: str,
        timestamp: str,
        signature: str
    ) -> bool:
        """
        Verify webhook request authenticity
        
        Args:
            body: Request body string
            timestamp: Request timestamp
            signature: Request signature
        
        Returns:
            True if signature is valid
        """
        pass
    
    @abstractmethod
    def parse_webhook_event(
        self,
        body: str,
        headers: Dict[str, str]
    ) -> WebhookEvent:
        """
        Parse incoming webhook event into platform-agnostic format
        
        Args:
            body: Request body
            headers: Request headers
        
        Returns:
            WebhookEvent with normalized data
        """
        pass
    
    @abstractmethod
    def create_access_request_modal(
        self,
        payload: AccessRequestPayload
    ) -> Dict[str, Any]:
        """
        Create access request modal/dialog
        
        Args:
            payload: Data for creating modal
        
        Returns:
            Platform-specific modal view dict
        """
        pass
    
    @abstractmethod
    def open_modal(
        self,
        trigger_id: str,
        view: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Open a modal/dialog
        
        Args:
            trigger_id: Platform-specific trigger identifier
            view: Modal view definition
            metadata: Additional metadata to store with modal
        
        Returns:
            Platform response
        """
        pass
    
    @abstractmethod
    def post_approval_message(
        self,
        payload: ApprovalMessagePayload
    ) -> Dict[str, Any]:
        """
        Post approval request message with action buttons
        
        Args:
            payload: Data for approval message
        
        Returns:
            Platform response with message identifier
        """
        pass
    
    @abstractmethod
    def update_message_status(
        self,
        payload: MessageUpdatePayload
    ) -> Dict[str, Any]:
        """
        Update message to show approval/denial status
        
        Args:
            payload: Data for message update
        
        Returns:
            Platform response
        """
        pass
    
    @abstractmethod
    def send_ephemeral_message(
        self,
        channel_id: str,
        user_id: str,
        text: str
    ) -> Dict[str, Any]:
        """
        Send ephemeral message visible only to specific user
        
        Args:
            channel_id: Channel identifier
            user_id: User identifier
            text: Message text (can include markdown)
        
        Returns:
            Platform response
        """
        pass
    
    @abstractmethod
    def send_notification(
        self,
        channel_id: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Send notification message to channel
        
        Args:
            channel_id: Channel identifier
            text: Message text
            blocks: Optional rich content blocks
        
        Returns:
            Platform response
        """
        pass
    
    @abstractmethod
    def get_user_by_email(
        self,
        email: str
    ) -> Optional[Dict[str, Any]]:
        """
        Look up user by email address
        
        Args:
            email: Email address
        
        Returns:
            User info dict or None if not found
        """
        pass
    
    @abstractmethod
    def get_user_email(
        self,
        user_id: str
    ) -> Optional[str]:
        """
        Get user email from user ID
        
        Args:
            user_id: Platform user identifier
        
        Returns:
            Email address or None if not found
        """
        pass
