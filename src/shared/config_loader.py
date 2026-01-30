"""
Configuration loader with caching for Lambda functions

Loads configuration from environment variables and Secrets Manager,
with module-level caching to optimize warm start performance.
"""

import os
import json
import boto3
from typing import Dict, Any, Optional
from aws_lambda_powertools import Logger

logger = Logger(child=True)

# Module-level cache (persists across warm invocations)
_secrets_cache: Dict[str, Any] = {}
_config_cache: Optional[Dict[str, Any]] = None


def get_config() -> Dict[str, Any]:
    """
    Get application configuration with caching
    
    Loads from environment variables and caches for subsequent invocations.
    Cache is invalidated on Lambda runtime recycling (typically 15-45 min).
    
    Returns:
        Dictionary containing all configuration values
    """
    global _config_cache
    
    if _config_cache is not None:
        logger.debug("Using cached configuration")
        return _config_cache
    
    logger.info("Loading configuration from environment")
    
    _config_cache = {
        'leases_table_name': os.environ['LEASES_TABLE_NAME'],
        'slack_secret_arn': os.environ['SLACK_SECRET_ARN'],
        'access_list_secret_arn': os.environ['ACCESS_LIST_SECRET_ARN'],
        'slack_channel_id': os.environ['SLACK_CHANNEL_ID'],
        'log_level': os.environ.get('LOG_LEVEL', 'INFO'),
        'dry_run': os.environ.get('DRY_RUN', 'false').lower() == 'true',
        'permission_durations': json.loads(os.environ.get('PERMISSION_DURATIONS', '[3600, 14400]')),
        'request_expiration_seconds': int(os.environ.get('REQUEST_EXPIRATION_SECONDS', '3600')),
        'reminder_interval_seconds': int(os.environ.get('REMINDER_INTERVAL_SECONDS', '900')),
        'reminder_backoff': float(os.environ.get('REMINDER_BACKOFF', '1.5')),
        'identity_center_instance_arn': os.environ['IDENTITY_CENTER_INSTANCE_ARN'],
        'identity_store_id': os.environ['IDENTITY_STORE_ID'],
        'audit_log_group_slack': os.environ.get('AUDIT_LOG_GROUP_SLACK', ''),
        'audit_log_group_revocation': os.environ.get('AUDIT_LOG_GROUP_REVOCATION', ''),
    }
    
    logger.info("Configuration loaded", extra={
        'dry_run': _config_cache['dry_run'],
        'log_level': _config_cache['log_level']
    })
    
    return _config_cache


def get_secret(secret_arn: str, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Get secret from Secrets Manager with caching
    
    Args:
        secret_arn: ARN of the secret to retrieve
        force_refresh: Force reload from Secrets Manager (bypass cache)
    
    Returns:
        Dictionary containing secret values
    """
    global _secrets_cache
    
    if not force_refresh and secret_arn in _secrets_cache:
        logger.debug("Using cached secret", extra={'secret_arn': secret_arn})
        return _secrets_cache[secret_arn]
    
    logger.info("Loading secret from Secrets Manager", extra={'secret_arn': secret_arn})
    
    try:
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_arn)
        secret_value = json.loads(response['SecretString'])
        
        # Cache the secret
        _secrets_cache[secret_arn] = secret_value
        
        logger.info("Secret loaded successfully", extra={'secret_arn': secret_arn})
        return secret_value
        
    except Exception as e:
        logger.error("Failed to load secret", extra={
            'secret_arn': secret_arn,
            'error': str(e)
        })
        raise


def get_slack_credentials() -> Dict[str, str]:
    """
    Get Slack credentials (bot_token, signing_secret)
    
    Returns:
        Dictionary with 'bot_token' and 'signing_secret' keys
    """
    config = get_config()
    return get_secret(config['slack_secret_arn'])


def get_access_list() -> Dict[str, Any]:
    """
    Get access list configuration (accounts, permission_sets, pseudo_groups)
    
    Returns:
        Dictionary with 'access_list' and 'pseudo_groups' keys
    """
    config = get_config()
    return get_secret(config['access_list_secret_arn'])


def parse_duration_to_seconds(time_str: str) -> int:
    """
    Parse hh:mm format to seconds
    
    Args:
        time_str: Time string in hh:mm format (e.g., "01:30")
    
    Returns:
        Duration in seconds
    """
    try:
        hours, minutes = time_str.split(':')
        return int(hours) * 3600 + int(minutes) * 60
    except (ValueError, AttributeError) as e:
        logger.error(f"Invalid time format: {time_str}", extra={'error': str(e)})
        raise ValueError(f"Time must be in hh:mm format, got: {time_str}")


def format_duration(seconds: int) -> str:
    """
    Format duration in seconds to human-readable string
    
    Args:
        seconds: Duration in seconds
    
    Returns:
        Formatted string (e.g., "4 hours", "1h 30m")
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0 and minutes > 0:
        return f"{hours}h {minutes}m"
    elif hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    elif minutes > 0:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        return f"{seconds} seconds"


def clear_cache() -> None:
    """
    Clear all caches (useful for testing)
    """
    global _secrets_cache, _config_cache
    _secrets_cache = {}
    _config_cache = None
    logger.debug("All caches cleared")
