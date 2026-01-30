"""
Processes webhook events from messaging platforms
(Slack, Teams, etc.) through the messaging port interface.

Handles:
- Message shortcuts (open access request modal)
- View submissions (validate and create approval requests)
- Block actions (approve/deny buttons)
"""

import json
from typing import Dict, Any
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.metrics import MetricUnit
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from shared.config_loader import get_config, get_slack_credentials, get_access_list, format_duration
from shared.access_normalizer import normalize_access_list, validate_access, get_account_options
from shared.messaging import (
    MessagingInterface,
    SlackMessagingAdapter,
    WebhookEventType,
    WebhookResponse,
    AccessRequestPayload,
    ApprovalMessagePayload,
    MessageUpdatePayload
)
from shared.identity_mapper import IdentityCenterMapper
from shared.lease_manager import LeaseManager
from shared.access_manager import AccessManager


logger = Logger(service="message_handler")
tracer = Tracer(service="message_handler")
metrics = Metrics(namespace="Apedemak", service="message_handler")

# Module-level caching
_messaging_adapter = None
_identity_mapper = None
_lease_manager = None
_normalized_access = None


def get_messaging_adapter() -> MessagingInterface:
    """Get cached messaging adapter (currently Slack)"""
    global _messaging_adapter
    if _messaging_adapter is None:
        credentials = get_slack_credentials()
        _messaging_adapter = SlackMessagingAdapter(
            bot_token=credentials['bot_token'],
            signing_secret=credentials['signing_secret']
        )
        logger.info("Messaging adapter initialized", extra={"platform": "slack"})
    return _messaging_adapter


def get_identity_mapper() -> IdentityCenterMapper:
    """Get cached Identity Center mapper"""
    global _identity_mapper
    if _identity_mapper is None:
        config = get_config()
        _identity_mapper = IdentityCenterMapper(
            instance_arn=config['identity_center_instance_arn'],
            identity_store_id=config['identity_store_id']
        )
        logger.info("Identity mapper initialized")
    return _identity_mapper


def get_lease_manager() -> LeaseManager:
    """Get cached lease manager"""
    global _lease_manager
    if _lease_manager is None:
        config = get_config()
        _lease_manager = LeaseManager(config['leases_table_name'])
        logger.info("Lease manager initialized")
    return _lease_manager


def get_normalized_access() -> Dict:
    """Get cached normalized access list"""
    global _normalized_access
    if _normalized_access is None:
        access_list = get_access_list()
        _normalized_access = normalize_access_list(access_list)
        logger.info("Access list normalized")
    return _normalized_access


@tracer.capture_method
def handle_message_shortcut(event: Any, messaging: MessagingInterface) -> WebhookResponse:
    """
    Handle message shortcut to open access request modal
    
    Args:
        event: Webhook event
        messaging: Messaging adapter
    
    Returns:
        WebhookResponse
    """
    logger.info("Handling message shortcut", extra={
        'user_id': event.user_id
    })
    
    config = get_config()
    normalized_access = get_normalized_access()
    accounts = get_account_options(normalized_access)
    
    # Create modal payload
    payload = AccessRequestPayload(
        accounts=accounts,
        permission_durations=config['permission_durations'],
        message_context={
            'text': event.metadata.get('message_text', ''),
            'user': event.metadata.get('message_user', ''),
            'ts': event.metadata.get('message_ts', '')
        }
    )
    
    modal = messaging.create_access_request_modal(payload)
    
    # Store context in metadata
    metadata = {
        'message_ts': event.metadata.get('message_ts'),
        'channel_id': event.metadata.get('channel_id'),
        'requester_id': event.user_id
    }
    
    messaging.open_modal(
        trigger_id=event.trigger_id,
        view=modal,
        metadata=metadata
    )
    
    metrics.add_metric(name="ModalOpened", unit=MetricUnit.Count, value=1)
    
    return WebhookResponse(status_code=200, body={})


@tracer.capture_method
def handle_view_submission(event: Any, messaging: MessagingInterface) -> WebhookResponse:
    """
    Handle modal view submission (access request)
    
    Validates access and either:
    - Creates approval message if approvers exist
    - Auto-approves and grants access if self-approval
    
    Args:
        event: Webhook event
        messaging: Messaging adapter
    
    Returns:
        WebhookResponse
    """
    logger.info("Handling view submission", extra={
        'user_id': event.user_id
    })
    
    view_data = event.view_data
    metadata = event.metadata
    
    account_id = view_data['account_id']
    permission_set = view_data['permission_set']
    duration_seconds = view_data['duration_seconds']
    justification = view_data['justification']
    
    channel_id = metadata['channel_id']
    message_ts = metadata.get('message_ts', '')
    
    config = get_config()
    dry_run = config['dry_run']
    identity_mapper = get_identity_mapper()
    lease_manager = get_lease_manager()
    normalized_access = get_normalized_access()
    
    # Get user email to find Identity Center principal ID
    user_email = messaging.get_user_email(event.user_id)
    if not user_email:
        return WebhookResponse(
            status_code=200,
            body={
                'response_action': 'errors',
                'errors': {
                    'permission_set_input': f"Could not retrieve email for user"
                }
            }
        )
    
    user_principal_id = identity_mapper.get_user_principal_id(user_email)
    if not user_principal_id:
        return WebhookResponse(
            status_code=200,
            body={
                'response_action': 'errors',
                'errors': {
                    'permission_set_input': f"User {user_email} not found in Identity Center"
                }
            }
        )
    
    user_groups = identity_mapper.get_user_groups(user_principal_id)
    
    validation = validate_access(
        user_email=user_email,
        account_id=account_id,
        permission_set=permission_set,
        user_groups=user_groups,
        normalized_access=normalized_access
    )
    
    if not validation.allowed:
        return WebhookResponse(
            status_code=200,
            body={
                'response_action': 'errors',
                'errors': {
                    'permission_set_input': validation.reason
                }
            }
        )
    
    permission_set_arn = identity_mapper.get_permission_set_arn(account_id, permission_set)
    if not permission_set_arn:
        return WebhookResponse(
            status_code=200,
            body={
                'response_action': 'errors',
                'errors': {
                    'permission_set_input': f"Permission set '{permission_set}' not found in account"
                }
            }
        )
    
    account_name = validation.account_name
    
    if validation.self_approve:
        logger.info("Self-approval: granting access immediately", extra={
            'user_email': user_email,
            'account': account_name,
            'permission_set': permission_set
        })
        
        if not dry_run:
            identity_mapper.create_account_assignment(
                account_id=account_id,
                permission_set_arn=permission_set_arn,
                principal_id=user_principal_id
            )
        
        lease_manager.create_lease(
            user_email=user_email,
            slack_user_id=event.user_id,
            account_id=account_id,
            account_name=account_name,
            permission_set=permission_set,
            duration_seconds=duration_seconds,
            justification=justification,
            slack_channel_id=channel_id,
            request_message_ts=message_ts,
            actioned_by=None,  # Self-approved
            dry_run=dry_run
        )
        
        confirmation_text = f"Access granted to **{account_name}** ({account_id})\n"
        confirmation_text += f"Permission Set: {permission_set}\n"
        confirmation_text += f"Duration: {format_duration(duration_seconds)}\n"
        if dry_run:
            confirmation_text += "\n👩🏾‍🔬 *DRY-RUN MODE* - No actual changes made"
        
        messaging.send_ephemeral_message(
            channel_id=channel_id,
            user_id=event.user_id,
            text=confirmation_text
        )
        
        metrics.add_metric(name="AccessSelfApproved", unit=MetricUnit.Count, value=1)
        
        return WebhookResponse(status_code=200, body={'response_action': 'clear'})
    
    # Request approval from approvers and create pending lease while we wait
    approval_payload = ApprovalMessagePayload(
        channel_id=channel_id,
        requester_id=event.user_id,
        requester_email=user_email,
        account_id=account_id,
        account_name=account_name,
        permission_set=permission_set,
        duration_seconds=duration_seconds,
        justification=justification,
        approver_emails=validation.approvers,
        dry_run=dry_run
    )
    
    approval_response = messaging.post_approval_message(approval_payload)
    approval_message_id = approval_response['message_id']
    
    lease_manager.create_lease(
        user_email=user_email,
        slack_user_id=event.user_id,
        account_id=account_id,
        account_name=account_name,
        permission_set=permission_set,
        duration_seconds=duration_seconds,
        justification=justification,
        slack_channel_id=channel_id,
        request_message_ts=approval_message_id,
        actioned_by='PENDING',
        dry_run=dry_run
    )
    
    metrics.add_metric(name="ApprovalRequested", unit=MetricUnit.Count, value=1)
    
    return WebhookResponse(status_code=200, body={'response_action': 'clear'})


@tracer.capture_method
def handle_button_action(event: Any, messaging: MessagingInterface) -> WebhookResponse:
    """
    Handle button action (approve/deny)
    
    Args:
        event: Webhook event
        messaging: Messaging adapter
    
    Returns:
        WebhookResponse
    """
    action_data = event.action_data
    action_id = action_data['action_id']
    identity_mapper = get_identity_mapper()
    lease_manager = get_lease_manager()
    config = get_config()
    dry_run = config['dry_run']
    
    logger.info("Handling button action", extra={
        'action_id': action_id,
        'user_id': event.user_id
    })
    
    # Parse action value (contains request details)
    value_data = json.loads(action_data['value'])
    user_email = value_data['requester_email']
    account_name = value_data['account_name']
    permission_set = value_data['permission_set']

    user_principal_id = identity_mapper.get_user_principal_id(user_email)
    aws_account_id = identity_mapper.get_account_id(account_name)
    if not user_principal_id:
        return WebhookResponse(
            status_code=200,
            body={
                'response_action': 'errors',
                'errors': {
                    'permission_set_input': f"User {user_email} not found in Identity Center"
                }
            }
        )

    pending_lease = lease_manager.get_lease_for_assignment(
        user_email=user_email,
        account_id=aws_account_id,
        permission_set=permission_set,
        status='PENDING'
    )

    if not pending_lease:
        logger.error("No pending lease found for approval", extra={
            'user_email': user_email,
            'account_name': account_name,
            'permission_set': permission_set
        })
        return WebhookResponse(
            status_code=200,
            body={
                'response_action': 'errors',
                'errors': {
                    'permission_set_input': f"No pending lease found for {user_email} on {account_name}"
                }
            }
        )
    if action_id == 'approve_access':
        # Handle approval
        logger.info("Access Approved", extra={'user_email': user_email,
                                                  'account_name': account_name,
                                                  'account_id': aws_account_id,
                                                  'permission_set': permission_set})

        permission_set_arn = identity_mapper.get_permission_set_arn(aws_account_id, permission_set)
        if not dry_run:
            identity_mapper.create_account_assignment(
                account_id=aws_account_id,
                permission_set_arn=permission_set_arn,
                principal_id=user_principal_id
            )

        # Update Lease status
        approver_email = messaging.get_user_email(event.user_id)
        lease_manager.update_lease_status(
            lease_id=pending_lease['lease_id'],
            status='ACTIVE',
            actioned_by=approver_email,
        )

        # Update message in channel with approval status
        update_payload = MessageUpdatePayload(
            channel_id=action_data['channel_id'],
            message_id=action_data['message_id'],
            account_name=account_name,
            permission_set=permission_set,
            duration_seconds=value_data['duration_seconds'],
            actor_id=event.user_id,
            approved=True,
            dry_run=dry_run
        )
        messaging.update_message_status(update_payload)

    elif action_id == 'deny_access':

        logger.info("Access Denied", extra={'user_email': user_email,
                                                  'account_name': account_name,
                                                  'account_id': aws_account_id,
                                                  'permission_set': permission_set})

        approver_email = messaging.get_user_email(event.user_id)
        lease_manager.update_lease_status(
            lease_id=pending_lease['lease_id'],
            status='DENIED',
            actioned_by=approver_email,
        )

        # Update message in channel with approval status
        update_payload = MessageUpdatePayload(
            channel_id=action_data['channel_id'],
            message_id=action_data['message_id'],
            account_name=account_name,
            permission_set=permission_set,
            duration_seconds=value_data['duration_seconds'],
            actor_id=event.user_id,
            approved=False,
            dry_run=dry_run
        )
        messaging.update_message_status(update_payload)

    return WebhookResponse(status_code=200, body={})


@tracer.capture_lambda_handler
@logger.inject_lambda_context
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for messaging platform webhook events
    
    Platform-agnostic handler that delegates to messaging adapter for
    platform-specific details.
    
    Args:
        event: API Gateway proxy event
        context: Lambda context
    
    Returns:
        API Gateway proxy response
    """
    logger.info("Processing webhook", extra={
        'path': event.get('path'),
        'method': event.get('httpMethod')
    })
    
    # Get request body and headers
    body = event.get('body', '')
    headers = event.get('headers', {})
    
    # Get messaging adapter
    messaging = get_messaging_adapter()
    
    # Verify webhook signature
    timestamp = headers.get('x-slack-request-timestamp', headers.get('X-Slack-Request-Timestamp', ''))
    signature = headers.get('x-slack-signature', headers.get('X-Slack-Signature', ''))
    
    if not messaging.verify_webhook_signature(body, timestamp, signature):
        logger.error("Invalid webhook signature")
        metrics.add_metric(name="SignatureVerificationFailed", unit=MetricUnit.Count, value=1)
        return {'statusCode': 401, 'body': json.dumps({'error': 'Unauthorized'})}
    
    # Parse webhook event
    webhook_event = messaging.parse_webhook_event(body, headers)
    
    # Handle URL verification challenge (Slack-specific but exposed through port)
    if webhook_event.event_type == WebhookEventType.URL_VERIFICATION:
        logger.info("URL verification challenge")
        return {
            'statusCode': 200,
            'body': json.dumps({'challenge': webhook_event.metadata.get('challenge')})
        }
    
    try:
        # Route to appropriate handler based on event type
        if webhook_event.event_type == WebhookEventType.MESSAGE_SHORTCUT:
            response = handle_message_shortcut(webhook_event, messaging)
        
        elif webhook_event.event_type == WebhookEventType.VIEW_SUBMISSION:
            response = handle_view_submission(webhook_event, messaging)
        
        elif webhook_event.event_type == WebhookEventType.BUTTON_ACTION:
            response = handle_button_action(webhook_event, messaging)
        
        else:
            logger.warning("Unknown event type", extra={'type': webhook_event.event_type})
            response = WebhookResponse(status_code=200, body={})
        
        # Convert WebhookResponse to API Gateway response
        return {
            'statusCode': response.status_code,
            'headers': response.headers or {'Content-Type': 'application/json'},
            'body': json.dumps(response.body) if response.body else ''
        }
    
    except Exception as e:
        logger.exception("Failed to process webhook")
        metrics.add_metric(name="WebhookError", unit=MetricUnit.Count, value=1)
        
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }

