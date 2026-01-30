"""
Access Revocation Lambda

Triggered by EventBridge schedule to:
1. Revoke expired access leases
2. Detect and revoke invalid direct assignments not in lease table
"""

import time
from typing import Dict, Any, List
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.utilities.typing import LambdaContext
from aws_lambda_powertools.metrics import MetricUnit

# Import shared modules
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from shared.config_loader import get_config, get_slack_credentials, get_access_list
from shared.access_normalizer import normalize_access_list
from shared.messaging import SlackMessagingAdapter, MessagingInterface
from shared.identity_mapper import IdentityCenterMapper
from shared.lease_manager import LeaseManager

# Initialize Lambda Powertools
logger = Logger(service="access_revocation")
tracer = Tracer(service="access_revocation")
metrics = Metrics(namespace="Apedemak", service="access_revocation")

# Module-level cache
_messaging_adapter = None
_identity_mapper = None
_lease_manager = None
_normalized_access = None


def get_messaging_adapter() -> MessagingInterface:
    """Get cached messaging adapter"""
    global _messaging_adapter
    if _messaging_adapter is None:
        credentials = get_slack_credentials()
        _messaging_adapter = SlackMessagingAdapter(
            bot_token=credentials['bot_token'],
            signing_secret=credentials['signing_secret']
        )
        logger.info("Messaging adapter initialized")
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
def revoke_expired_leases(config: Dict) -> int:
    """
    Query and revoke all expired leases
    
    Args:
        config: Application configuration
    
    Returns:
        Number of leases revoked
    """
    logger.info("Checking for expired leases")
    
    lease_manager = get_lease_manager()
    identity_mapper = get_identity_mapper()
    messaging = get_messaging_adapter()
    
    # Get expired leases from DynamoDB
    expired_leases = lease_manager.get_expired_leases(limit=100)
    
    if not expired_leases:
        logger.info("No expired leases found")
        return 0
    
    logger.info(f"Found {len(expired_leases)} expired leases")
    
    revoked_count = 0
    dry_run = config['dry_run']
    
    for lease in expired_leases:
        lease_id = lease['lease_id']
        user_email = lease['user_email']
        account_id = lease['account_id']
        account_name = lease['account_name']
        permission_set = lease['permission_set']
        
        logger.info("Processing expired lease", extra={
            'lease_id': lease_id,
            'user_email': user_email,
            'account': account_name,
            'permission_set': permission_set
        })
        
        try:
            # Get user principal ID
            principal_id = identity_mapper.get_user_principal_id(user_email)
            if not principal_id:
                logger.warning("User not found in Identity Center", extra={
                    'user_email': user_email,
                    'lease_id': lease_id
                })
                # Mark as expired anyway
                lease_manager.mark_lease_expired(lease_id)
                continue
            
            # Get permission set ARN
            permission_set_arn = identity_mapper.get_permission_set_arn(
                account_id, permission_set
            )
            if not permission_set_arn:
                logger.warning("Permission set not found", extra={
                    'permission_set': permission_set,
                    'account_id': account_id,
                    'lease_id': lease_id
                })
                lease_manager.mark_lease_expired(lease_id)
                continue
            
            # Revoke access (unless dry-run)
            if not dry_run:
                identity_mapper.delete_account_assignment(
                    account_id=account_id,
                    permission_set_arn=permission_set_arn,
                    principal_id=principal_id
                )
                logger.info("Access revoked", extra={
                    'user_email': user_email,
                    'account': account_name,
                    'permission_set': permission_set
                })
            else:
                logger.info("DRY-RUN: Would revoke access", extra={
                    'user_email': user_email,
                    'account': account_name,
                    'permission_set': permission_set
                })
            
            # Update lease status
            lease_manager.mark_lease_expired(lease_id)
            
            # Notify in Slack (if channel configured and not dry-run notification disabled)
            if config['slack_channel_id']:
                notification_text = f"⏰ Access expired and revoked\n"
                notification_text += f"User: {user_email}\n"
                notification_text += f"Account: **{account_name}** ({account_id})\n"
                notification_text += f"Permission Set: {permission_set}\n"
                if dry_run:
                    notification_text += "\n🧪 *DRY-RUN MODE* - Access would have been revoked"
                
                try:
                    messaging.send_notification(
                        channel_id=config['slack_channel_id'],
                        text=notification_text
                    )
                except Exception as e:
                    logger.error("Failed to send notification", extra={'error': str(e)})
            
            revoked_count += 1
            
        except Exception as e:
            logger.error("Failed to revoke lease", extra={
                'lease_id': lease_id,
                'error': str(e)
            })
            # Continue processing other leases
    
    logger.info(f"Revoked {revoked_count} expired leases")
    metrics.add_metric(name="LeasesRevoked", unit=MetricUnit.Count, value=revoked_count)
    
    return revoked_count


@tracer.capture_method
def check_invalid_direct_assignments(config: Dict) -> int:
    """
    Check for direct assignments that don't have leases and revoke them
    
    This catches cases where:
    - Someone manually assigned access outside Apedemak
    - A lease was deleted but assignment remains
    
    Args:
        config: Application configuration
    
    Returns:
        Number of invalid assignments revoked
    """
    logger.info("Checking for invalid direct assignments")
    
    lease_manager = get_lease_manager()
    identity_mapper = get_identity_mapper()
    normalized_access = get_normalized_access()
    
    revoked_count = 0
    dry_run = config['dry_run']
    
    # Iterate through configured accounts and permission sets
    for account_id, account_data in normalized_access.items():
        account_name = account_data['account_name']
        
        for permission_set_name in account_data['permission_sets'].keys():
            try:
                # Get permission set ARN
                permission_set_arn = identity_mapper.get_permission_set_arn(
                    account_id, permission_set_name
                )
                if not permission_set_arn:
                    continue
                
                # List all current assignments for this permission set
                assignments = identity_mapper.list_account_assignments(
                    account_id=account_id,
                    permission_set_arn=permission_set_arn
                )
                
                # Check each USER assignment (ignore GROUP assignments)
                for assignment in assignments:
                    if assignment['PrincipalType'] != 'USER':
                        continue
                    
                    principal_id = assignment['PrincipalId']
                    
                    # Get user email
                    try:
                        user_info = identity_mapper.identity_store.describe_user(
                            IdentityStoreId=identity_mapper.identity_store_id,
                            UserId=principal_id
                        )
                        user_email = user_info.get('UserName', '')
                        
                        if not user_email:
                            # Try to get from emails attribute
                            emails = user_info.get('Emails', [])
                            if emails:
                                user_email = emails[0].get('Value', '')
                        
                        if not user_email:
                            logger.warning("Could not determine user email", extra={
                                'principal_id': principal_id
                            })
                            continue
                        
                    except Exception as e:
                        logger.error("Failed to get user info", extra={
                            'principal_id': principal_id,
                            'error': str(e)
                        })
                        continue
                    
                    # Check if there's an active lease for this assignment
                    active_lease = lease_manager.get_lease_for_assignment(
                        user_email=user_email,
                        account_id=account_id,
                        permission_set=permission_set_name
                    )
                    
                    if not active_lease:
                        # No active lease - this is an invalid direct assignment
                        logger.warning("Found invalid direct assignment", extra={
                            'user_email': user_email,
                            'account': account_name,
                            'permission_set': permission_set_name
                        })
                        
                        # Revoke it (unless dry-run)
                        if not dry_run:
                            identity_mapper.delete_account_assignment(
                                account_id=account_id,
                                permission_set_arn=permission_set_arn,
                                principal_id=principal_id
                            )
                            logger.info("Revoked invalid direct assignment", extra={
                                'user_email': user_email,
                                'account': account_name,
                                'permission_set': permission_set_name
                            })
                        else:
                            logger.info("DRY-RUN: Would revoke invalid assignment", extra={
                                'user_email': user_email,
                                'account': account_name,
                                'permission_set': permission_set_name
                            })
                        
                        revoked_count += 1
                
            except Exception as e:
                logger.error("Failed to check assignments", extra={
                    'account_id': account_id,
                    'permission_set': permission_set_name,
                    'error': str(e)
                })
                # Continue with other permission sets
    
    logger.info(f"Revoked {revoked_count} invalid direct assignments")
    metrics.add_metric(name="InvalidAssignmentsRevoked", unit=MetricUnit.Count, value=revoked_count)
    
    return revoked_count


@tracer.capture_lambda_handler
@logger.inject_lambda_context
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Main Lambda handler for scheduled access revocation
    
    Triggered by EventBridge schedule to:
    1. Revoke expired access leases
    2. Detect and revoke invalid direct assignments
    
    Args:
        event: EventBridge event
        context: Lambda context
    
    Returns:
        Dict with summary of actions taken
    """
    logger.info("Access revocation check started")
    
    config = get_config()
    
    try:
        # Step 1: Revoke expired leases
        expired_leases_count = revoke_expired_leases(config)
        
        # Step 2: Check for invalid direct assignments
        invalid_assignments_count = check_invalid_direct_assignments(config)
        
        result = {
            'expired_leases_revoked': expired_leases_count,
            'invalid_assignments_revoked': invalid_assignments_count,
            'dry_run': config['dry_run']
        }
        
        logger.info("Access revocation check completed", extra=result)
        
        return {
            'statusCode': 200,
            'body': result
        }
        
    except Exception as e:
        logger.exception("Access revocation check failed")
        metrics.add_metric(name="RevocationCheckError", unit=MetricUnit.Count, value=1)
        
        return {
            'statusCode': 500,
            'body': {'error': str(e)}
        }
