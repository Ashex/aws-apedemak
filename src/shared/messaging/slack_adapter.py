"""
Slack Messaging Adapter

Concrete implementation of interface for Slack.
"""

import json
import hmac
import hashlib
import time
import urllib.parse
from typing import Dict, List, Any, Optional
from aws_lambda_powertools import Logger
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .interface import (
    MessagingInterface,
    AccessRequestPayload,
    ApprovalMessagePayload,
    MessageUpdatePayload,
    WebhookEvent,
    WebhookEventType,
    WebhookResponse
)

logger = Logger(child=True)


class SlackMessagingAdapter(MessagingInterface):
    """Slack-specific implementation of messaging"""
    
    def __init__(self, bot_token: str, signing_secret: str):
        """
        Initialize Slack adapter
        
        Args:
            bot_token: Slack bot OAuth token
            signing_secret: Slack signing secret for signature verification
        """
        self.client = WebClient(token=bot_token)
        self.signing_secret = signing_secret
    
    def verify_webhook_signature(
        self,
        body: str,
        timestamp: str,
        signature: str
    ) -> bool:
        """
        Verify Slack request signature
        
        Args:
            body: Request body string
            timestamp: X-Slack-Request-Timestamp header
            signature: X-Slack-Signature header
        
        Returns:
            True if signature is valid
        """
        # Check timestamp to prevent replay attacks (must be within 5 minutes)
        try:
            current_time = int(time.time())
            if abs(current_time - int(timestamp)) > 300:
                logger.warning("Request timestamp too old")
                return False
        except (ValueError, TypeError):
            logger.warning("Invalid timestamp format")
            return False
        
        sig_basestring = f"v0:{timestamp}:{body}".encode('utf-8')
        computed_signature = 'v0=' + hmac.new(
            self.signing_secret.encode('utf-8'),
            sig_basestring,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed_signature, signature)
    
    def parse_webhook_event(
        self,
        body: str,
        headers: Dict[str, str]
    ) -> WebhookEvent:
        """
        Parse Slack webhook event into platform-agnostic format
        
        Args:
            body: Request body
            headers: Request headers
        
        Returns:
            WebhookEvent with normalized data
        """
        # Parse payload
        content_type = headers.get('content-type', headers.get('Content-Type', ''))
        
        if 'application/json' in content_type:
            payload = json.loads(body)
        else:
            # Form-encoded payload
            params = urllib.parse.parse_qs(body)
            payload = json.loads(params.get('payload', ['{}'])[0])
        
        # Determine event type
        payload_type = payload.get('type')
        
        if payload_type == 'url_verification':
            return WebhookEvent(
                event_type=WebhookEventType.URL_VERIFICATION,
                raw_payload=payload,
                user_id='',
                metadata={'challenge': payload.get('challenge')}
            )
        
        elif payload_type == 'message_action':
            # Message shortcut
            user = payload.get('user', {})
            message = payload.get('message', {})
            
            return WebhookEvent(
                event_type=WebhookEventType.MESSAGE_SHORTCUT,
                raw_payload=payload,
                user_id=user.get('id', ''),
                trigger_id=payload.get('trigger_id'),
                metadata={
                    'channel_id': payload.get('channel', {}).get('id'),
                    'message_ts': message.get('ts'),
                    'message_text': message.get('text', '')[:200],
                    'message_user': message.get('user', '')
                }
            )
        
        elif payload_type == 'view_submission':
            # Modal submission
            view = payload.get('view', {})
            user = payload.get('user', {})
            values = view.get('state', {}).get('values', {})
            private_metadata = json.loads(view.get('private_metadata', '{}'))
            
            # Extract form values
            account_id = values.get('account_select', {}).get('account', {}).get('selected_option', {}).get('value')
            permission_set = values.get('permission_set_input', {}).get('permission_set', {}).get('value', '').strip()
            duration_seconds = int(values.get('duration_select', {}).get('duration', {}).get('selected_option', {}).get('value', '0'))
            justification = values.get('justification', {}).get('justification_text', {}).get('value', '').strip()
            
            return WebhookEvent(
                event_type=WebhookEventType.VIEW_SUBMISSION,
                raw_payload=payload,
                user_id=user.get('id', ''),
                view_data={
                    'account_id': account_id,
                    'permission_set': permission_set,
                    'duration_seconds': duration_seconds,
                    'justification': justification
                },
                metadata=private_metadata
            )
        
        elif payload_type == 'block_actions':
            # Button click
            actions = payload.get('actions', [])
            action = actions[0] if actions else {}
            user = payload.get('user', {})
            
            return WebhookEvent(
                event_type=WebhookEventType.BUTTON_ACTION,
                raw_payload=payload,
                user_id=user.get('id', ''),
                action_data={
                    'action_id': action.get('action_id'),
                    'value': action.get('value'),
                    'channel_id': payload.get('channel', {}).get('id'),
                    'message_ts': payload.get('message', {}).get('ts')
                }
            )
        
        else:
            return WebhookEvent(
                event_type=WebhookEventType.UNKNOWN,
                raw_payload=payload,
                user_id='',
                metadata={'original_type': payload_type}
            )
    
    def create_access_request_modal(
        self,
        payload: AccessRequestPayload
    ) -> Dict[str, Any]:
        """
        Create Slack access request modal with Block Kit
        
        Args:
            payload: Data for creating modal
        
        Returns:
            Slack modal view dict
        """
        from shared.config_loader import format_duration
        
        # Create account options for dropdown
        account_options = [
            {
                "text": {"type": "plain_text", "text": acc['name']},
                "value": acc['id']
            }
            for acc in payload.accounts
        ]
        
        # Create duration options
        duration_options = [
            {
                "text": {"type": "plain_text", "text": format_duration(dur)},
                "value": str(dur)
            }
            for dur in sorted(payload.permission_durations)
        ]
        
        blocks = []
        
        # Add context if provided
        if payload.message_context:
            blocks.extend([
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Context from message:*\n>{payload.message_context.get('text', 'N/A')}"
                    }
                },
                {"type": "divider"}
            ])
        
        # Account selection
        blocks.append({
            "type": "input",
            "block_id": "account_select",
            "label": {"type": "plain_text", "text": "AWS Account"},
            "element": {
                "type": "static_select",
                "action_id": "account",
                "placeholder": {"type": "plain_text", "text": "Select an account"},
                "options": account_options
            }
        })
        
        # Permission set input
        blocks.append({
            "type": "input",
            "block_id": "permission_set_input",
            "label": {"type": "plain_text", "text": "Permission Set"},
            "element": {
                "type": "plain_text_input",
                "action_id": "permission_set",
                "placeholder": {"type": "plain_text", "text": "e.g., ReadOnlyAccess, DeveloperAccess"}
            }
        })
        
        # Duration selection
        blocks.append({
            "type": "input",
            "block_id": "duration_select",
            "label": {"type": "plain_text", "text": "Duration"},
            "element": {
                "type": "static_select",
                "action_id": "duration",
                "placeholder": {"type": "plain_text", "text": "Select duration"},
                "options": duration_options,
                "initial_option": duration_options[0] if duration_options else None
            }
        })
        
        # Justification
        blocks.append({
            "type": "input",
            "block_id": "justification",
            "label": {"type": "plain_text", "text": "Justification"},
            "element": {
                "type": "plain_text_input",
                "action_id": "justification_text",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "Why do you need this access?"}
            }
        })
        
        return {
            "type": "modal",
            "callback_id": "access_request_submit",
            "title": {"type": "plain_text", "text": "Request Access"},
            "submit": {"type": "plain_text", "text": "Submit Request"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": blocks
        }
    
    def open_modal(
        self,
        trigger_id: str,
        view: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Open a modal in Slack
        
        Args:
            trigger_id: Slack trigger ID from interaction
            view: Modal view dict
            metadata: Additional metadata to store with modal
        
        Returns:
            Slack API response
        """
        if metadata:
            view['private_metadata'] = json.dumps(metadata)
        
        try:
            response = self.client.views_open(trigger_id=trigger_id, view=view)
            logger.info("Modal opened", extra={"view_id": response['view']['id']})
            return response
        except SlackApiError as e:
            logger.error("Failed to open modal", extra={"error": str(e)})
            raise
    
    def post_approval_message(
        self,
        payload: ApprovalMessagePayload
    ) -> Dict[str, Any]:
        """
        Post approval request message with Slack Block Kit
        
        Args:
            payload: Data for approval message
        
        Returns:
            Slack API response with message timestamp
        """
        from shared.config_loader import format_duration
        
        # Convert approver emails to Slack user IDs
        approver_user_ids = []
        for approver_email in payload.approver_emails:
            user = self.get_user_by_email(approver_email)
            if user:
                approver_user_ids.append(user['id'])
        
        if not approver_user_ids:
            logger.warning("No approvers found in Slack", extra={
                'approver_emails': payload.approver_emails
            })
            # Still post message but without mentions
            approver_mentions = ', '.join(payload.approver_emails)
        else:
            approver_mentions = ' '.join([f"<@{uid}>" for uid in approver_user_ids])
        
        blocks = []
        
        # Dry-run indicator
        if payload.dry_run:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "👩🏾‍🔬 *DRY-RUN MODE* - No actual changes will be made"
                }]
            })
        
        # Request details
        blocks.extend([
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🔐 Access Request"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Requester:*\n<@{payload.requester_id}>"},
                    {"type": "mrkdwn", "text": f"*Account:*\n{payload.account_name}"},
                    {"type": "mrkdwn", "text": f"*Permission Set:*\n{payload.permission_set}"},
                    {"type": "mrkdwn", "text": f"*Duration:*\n{format_duration(payload.duration_seconds)}"},
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Justification:*\n{payload.justification}"}
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Approvers:* {approver_mentions}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "style": "primary",
                    "action_id": "approve_access",
                    "value": json.dumps({
                        'account_id': payload.account_id,
                        'permission_set': payload.permission_set,
                        'requester_email': payload.requester_email
                    })
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Deny"},
                        "style": "danger",
                        "action_id": "deny_access",
                        "value": json.dumps({
                            'requester_email': payload.requester_email
                        })
                    }
                ]
            }
        ])
        
        try:
            response = self.client.chat_postMessage(
                channel=payload.channel_id,
                blocks=blocks,
                text=f"Access request from <@{payload.requester_id}> for {payload.account_name}"
            )
            logger.info("Approval message posted", extra={
                "channel": payload.channel_id,
                "message_ts": response['ts']
            })
            return {'message_id': response['ts'], 'channel_id': payload.channel_id}
        except SlackApiError as e:
            logger.error("Failed to post approval message", extra={"error": str(e)})
            raise
    
    def update_message_status(
        self,
        payload: MessageUpdatePayload
    ) -> Dict[str, Any]:
        """
        Update Slack message to show approval/denial status
        
        Args:
            payload: Data for message update
        
        Returns:
            Slack API response
        """
        from shared.config_loader import format_duration
        
        blocks = []
        
        if payload.dry_run:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "👩🏾‍🔬 *DRY-RUN MODE* - No actual changes were made"
                }]
            })
        
        if payload.approved:
            blocks.extend([
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "✅ Access Request Approved"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Account:*\n{payload.account_name}"},
                        {"type": "mrkdwn", "text": f"*Permission Set:*\n{payload.permission_set}"},
                        {"type": "mrkdwn", "text": f"*Duration:*\n{format_duration(payload.duration_seconds)}"},
                        {"type": "mrkdwn", "text": f"*Approved by:*\n<@{payload.actor_id}>"},
                    ]
                }
            ])
            text = "Access request approved"
        else:
            blocks.extend([
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "❌ Access Request Denied"}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"Denied by <@{payload.actor_id}>"}
                }
            ])
            text = "Access request denied"
        
        try:
            response = self.client.chat_update(
                channel=payload.channel_id,
                ts=payload.message_id,
                blocks=blocks,
                text=text
            )
            logger.info(f"Message updated to {'approved' if payload.approved else 'denied'} status")
            return response
        except SlackApiError as e:
            logger.error("Failed to update message", extra={"error": str(e)})
            raise
    
    def send_ephemeral_message(
        self,
        channel_id: str,
        user_id: str,
        text: str
    ) -> Dict[str, Any]:
        """
        Send ephemeral Slack message visible only to specific user
        
        Args:
            channel_id: Slack channel ID
            user_id: Slack user ID to show message to
            text: Message text (markdown supported)
        
        Returns:
            Slack API response
        """
        try:
            response = self.client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=text
            )
            return response
        except SlackApiError as e:
            logger.error("Failed to post ephemeral message", extra={"error": str(e)})
            raise
    
    def send_notification(
        self,
        channel_id: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Send notification message to Slack channel
        
        Args:
            channel_id: Slack channel ID
            text: Message text
            blocks: Optional Block Kit blocks for rich formatting
        
        Returns:
            Slack API response
        """
        try:
            response = self.client.chat_postMessage(
                channel=channel_id,
                text=text,
                blocks=blocks
            )
            return response
        except SlackApiError as e:
            logger.error("Failed to send notification", extra={"error": str(e)})
            raise
    
    def get_user_by_email(
        self,
        email: str
    ) -> Optional[Dict[str, Any]]:
        """
        Look up Slack user by email address
        
        Args:
            email: Email address
        
        Returns:
            User dict or None if not found
        """
        try:
            response = self.client.users_lookupByEmail(email=email)
            return response.get('user')
        except SlackApiError as e:
            if e.response['error'] == 'users_not_found':
                logger.warning(f"Slack user not found for email: {email}")
                return None
            logger.error("Failed to lookup user by email", extra={"error": str(e)})
            raise
    
    def get_user_email(
        self,
        user_id: str
    ) -> Optional[str]:
        """
        Get user email from Slack user ID
        
        Args:
            user_id: Slack user ID
        
        Returns:
            Email address or None if not found
        """
        try:
            response = self.client.users_info(user=user_id)
            return response['user']['profile'].get('email')
        except SlackApiError as e:
            logger.error("Failed to get user info", extra={"error": str(e)})
            return None
