"""
Unit tests for config_loader module
"""

import pytest
import json
from src.shared.config_loader import (
    get_config,
    get_secret,
    get_slack_credentials,
    get_access_list,
    format_duration,
    parse_duration_to_seconds,
    clear_cache
)


def test_get_config(mock_config):
    """Test loading configuration from environment"""
    config = get_config()
    
    assert config['leases_table_name'] == 'test-leases'
    assert config['slack_channel_id'] == 'C0123456789'
    assert config['log_level'] == 'INFO'
    assert config['dry_run'] is False
    assert config['permission_durations'] == [3600, 14400]


def test_get_config_caching(mock_config):
    """Test that config is cached on subsequent calls"""
    config1 = get_config()
    config2 = get_config()
    
    # Should return same object (cached)
    assert config1 is config2


def test_get_config_cache_cleared(mock_config):
    """Test that clearing cache reloads config"""
    config1 = get_config()
    clear_cache()
    config2 = get_config()
    
    # Should be different objects after cache clear
    assert config1 is not config2
    # But same values
    assert config1 == config2


def test_get_secret(aws_credentials, secrets_manager):
    """Test loading secret from Secrets Manager"""
    secret = get_secret('arn:aws:secretsmanager:us-east-1:123456789012:secret:test-slack')
    
    assert 'bot_token' in secret
    assert 'signing_secret' in secret
    assert secret['bot_token'] == 'xoxb-test-token'


def test_get_secret_caching(aws_credentials, secrets_manager):
    """Test that secrets are cached"""
    secret_arn = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:test-slack'
    
    secret1 = get_secret(secret_arn)
    secret2 = get_secret(secret_arn)
    
    assert secret1 is secret2


def test_get_secret_force_refresh(aws_credentials, secrets_manager):
    """Test forcing secret refresh bypasses cache"""
    secret_arn = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:test-slack'
    
    secret1 = get_secret(secret_arn)
    secret2 = get_secret(secret_arn, force_refresh=True)
    
    # Different objects but same values
    assert secret1 is not secret2
    assert secret1 == secret2


def test_get_slack_credentials(mock_config, aws_credentials, secrets_manager):
    """Test getting Slack credentials"""
    creds = get_slack_credentials()
    
    assert 'bot_token' in creds
    assert 'signing_secret' in creds
    assert creds['bot_token'].startswith('xoxb-')


def test_get_access_list(mock_config, aws_credentials, secrets_manager, sample_access_config):
    """Test getting access list configuration"""
    access_list = get_access_list()
    
    assert 'access_list' in access_list
    assert 'pseudo_groups' in access_list
    assert len(access_list['access_list']['accounts']) == 2


def test_format_duration_hours():
    """Test duration formatting for hours"""
    assert format_duration(3600) == '1 hour'
    assert format_duration(7200) == '2 hours'
    assert format_duration(14400) == '4 hours'


def test_format_duration_minutes():
    """Test duration formatting for minutes"""
    assert format_duration(60) == '1 minute'
    assert format_duration(1800) == '30 minutes'
    assert format_duration(3000) == '50 minutes'


def test_format_duration_hours_and_minutes():
    """Test duration formatting for hours and minutes"""
    assert format_duration(5400) == '1h 30m'
    assert format_duration(9000) == '2h 30m'


def test_format_duration_seconds():
    """Test duration formatting for seconds"""
    assert format_duration(30) == '30 seconds'
    assert format_duration(45) == '45 seconds'


def test_parse_duration_to_seconds_hours():
    """Test parsing hh:mm format - hours only"""
    assert parse_duration_to_seconds('01:00') == 3600
    assert parse_duration_to_seconds('04:00') == 14400
    assert parse_duration_to_seconds('08:00') == 28800


def test_parse_duration_to_seconds_minutes():
    """Test parsing hh:mm format - minutes only"""
    assert parse_duration_to_seconds('00:30') == 1800
    assert parse_duration_to_seconds('00:15') == 900
    assert parse_duration_to_seconds('00:45') == 2700


def test_parse_duration_to_seconds_combined():
    """Test parsing hh:mm format - hours and minutes"""
    assert parse_duration_to_seconds('01:30') == 5400
    assert parse_duration_to_seconds('02:45') == 9900
    assert parse_duration_to_seconds('03:15') == 11700


def test_parse_duration_to_seconds_invalid_format():
    """Test parsing invalid time format"""
    with pytest.raises(ValueError, match="Time must be in hh:mm format"):
        parse_duration_to_seconds('invalid')
    
    with pytest.raises(ValueError, match="Time must be in hh:mm format"):
        parse_duration_to_seconds('1:2:3')
