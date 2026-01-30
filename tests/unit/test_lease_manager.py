"""
Unit tests for lease_manager module
"""

import pytest
import time
from src.shared.lease_manager import LeaseManager


def test_create_lease(mock_config, dynamodb_table):
    """Test creating a new lease"""
    manager = LeaseManager('test-leases')
    
    lease = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123456',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456',
        actioned_by='approver@example.com',
        dry_run=False
    )
    
    assert 'lease_id' in lease
    assert lease['lease_id'].startswith('lease_')
    assert lease['user_email'] == 'user@example.com'
    assert lease['account_name'] == 'Production'
    assert lease['status'] == 'ACTIVE'
    assert lease['duration_seconds'] == 3600
    assert 'expires_at' in lease
    assert 'ttl' in lease


def test_get_lease(mock_config, dynamodb_table):
    """Test retrieving a lease by ID"""
    manager = LeaseManager('test-leases')
    
    # Create lease
    created = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    # Retrieve lease
    retrieved = manager.get_lease(created['lease_id'])
    
    assert retrieved is not None
    assert retrieved['lease_id'] == created['lease_id']
    assert retrieved['user_email'] == 'user@example.com'


def test_get_lease_not_found(mock_config, dynamodb_table):
    """Test retrieving non-existent lease"""
    manager = LeaseManager('test-leases')
    
    lease = manager.get_lease('nonexistent_lease_id')
    
    assert lease is None


def test_get_expired_leases(mock_config, dynamodb_table):
    """Test querying expired leases"""
    manager = LeaseManager('test-leases')
    
    current_time = int(time.time())
    
    # Create expired lease (expires in past)
    expired_lease = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=-3600,  # Negative duration = already expired
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    # Create active lease (expires in future)
    active_lease = manager.create_lease(
        user_email='user2@example.com',
        slack_user_id='U456',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    # Query expired leases
    expired = manager.get_expired_leases()
    
    assert len(expired) == 1
    assert expired[0]['lease_id'] == expired_lease['lease_id']


def test_get_user_leases(mock_config, dynamodb_table):
    """Test querying leases for a user"""
    manager = LeaseManager('test-leases')
    
    # Create leases for user
    lease1 = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing 1',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    time.sleep(0.1)  # Ensure different created_at timestamps
    
    lease2 = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='210987654321',
        account_name='Staging',
        permission_set='DeveloperAccess',
        duration_seconds=7200,
        justification='Testing 2',
        slack_channel_id='C123',
        request_message_ts='1234567890.123457'
    )
    
    # Create lease for different user
    lease3 = manager.create_lease(
        user_email='other@example.com',
        slack_user_id='U789',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing 3',
        slack_channel_id='C123',
        request_message_ts='1234567890.123458'
    )
    
    # Query user leases
    user_leases = manager.get_user_leases('user@example.com')
    
    assert len(user_leases) == 2
    # Should be in descending order (newest first)
    assert user_leases[0]['created_at'] >= user_leases[1]['created_at']


def test_update_lease_status(mock_config, dynamodb_table):
    """Test updating lease status"""
    manager = LeaseManager('test-leases')
    
    # Create lease
    lease = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    # Update status
    manager.update_lease_status(lease['lease_id'], 'EXPIRED')
    
    # Retrieve and verify
    updated = manager.get_lease(lease['lease_id'])
    assert updated['status'] == 'EXPIRED'


def test_revoke_lease(mock_config, dynamodb_table):
    """Test revoking a lease"""
    manager = LeaseManager('test-leases')
    
    # Create lease
    lease = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    # Revoke lease
    manager.revoke_lease(lease['lease_id'])
    
    # Retrieve and verify
    revoked = manager.get_lease(lease['lease_id'])
    assert revoked['status'] == 'REVOKED'
    assert 'revoked_at' in revoked


def test_mark_lease_expired(mock_config, dynamodb_table):
    """Test marking lease as expired"""
    manager = LeaseManager('test-leases')
    
    # Create lease
    lease = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    # Mark as expired
    manager.mark_lease_expired(lease['lease_id'])
    
    # Retrieve and verify
    expired = manager.get_lease(lease['lease_id'])
    assert expired['status'] == 'EXPIRED'


def test_get_active_lease_for_assignment(mock_config, dynamodb_table):
    """Test checking for active lease for specific assignment"""
    manager = LeaseManager('test-leases')
    
    # Create lease
    lease = manager.create_lease(
        user_email='user@example.com',
        slack_user_id='U123',
        account_id='123456789012',
        account_name='Production',
        permission_set='ReadOnlyAccess',
        duration_seconds=3600,
        justification='Testing',
        slack_channel_id='C123',
        request_message_ts='1234567890.123456'
    )
    
    # Check for active lease
    active = manager.get_lease_for_assignment(
        user_email='user@example.com',
        account_id='123456789012',
        permission_set='ReadOnlyAccess'
    )
    
    assert active is not None
    assert active['lease_id'] == lease['lease_id']
    
    # Check for non-existent assignment
    none_lease = manager.get_lease_for_assignment(
        user_email='user@example.com',
        account_id='123456789012',
        permission_set='DifferentPermissionSet'
    )
    
    assert none_lease is None
