"""
Unit tests for access_normalizer module
"""

import pytest
from src.shared.access_normalizer import (
    normalize_access_list,
    validate_access,
    is_user_in_pseudo_group,
    get_user_pseudo_groups,
    get_account_options,
    get_permission_set_options
)


def test_normalize_access_list(sample_access_config):
    """Test access list normalization"""
    result = normalize_access_list(sample_access_config)
    
    # Check accounts exist
    assert '123456789012' in result
    assert '210987654321' in result
    
    # Check account names
    assert result['123456789012']['account_name'] == 'Production'
    assert result['210987654321']['account_name'] == 'Staging'
    
    # Check permission sets
    prod_psets = result['123456789012']['permission_sets']
    assert 'ReadOnlyAccess' in prod_psets
    assert 'DeveloperAccess' in prod_psets
    
    # Check users are in set format
    assert isinstance(prod_psets['ReadOnlyAccess']['allowed_users'], set)
    assert 'user@example.com' in prod_psets['ReadOnlyAccess']['allowed_users']
    
    # Check approvers
    assert prod_psets['ReadOnlyAccess']['approvers'] == ['approver@example.com']
    assert prod_psets['ReadOnlyAccess']['self_approve'] is False
    
    # Check self-approval
    assert prod_psets['DeveloperAccess']['self_approve'] is True


def test_is_user_in_pseudo_group(sample_access_config):
    """Test pseudo-group membership check"""
    normalize_access_list(sample_access_config)  # Initialize cache
    
    assert is_user_in_pseudo_group('senior1@example.com', 'pseudo:senior-engineers') is True
    assert is_user_in_pseudo_group('senior2@example.com', 'pseudo:senior-engineers') is True
    assert is_user_in_pseudo_group('user@example.com', 'pseudo:senior-engineers') is False
    assert is_user_in_pseudo_group('senior1@example.com', 'non-existent') is False


def test_get_user_pseudo_groups(sample_access_config):
    """Test getting all pseudo-groups for a user"""
    normalize_access_list(sample_access_config)
    
    groups = get_user_pseudo_groups('senior1@example.com')
    assert 'pseudo:senior-engineers' in groups
    
    groups = get_user_pseudo_groups('user@example.com')
    assert len(groups) == 0


def test_validate_access_direct_user(sample_access_config):
    """Test access validation for direct user assignment"""
    normalized = normalize_access_list(sample_access_config)
    
    result = validate_access(
        user_email='user@example.com',
        account_id='123456789012',
        permission_set='ReadOnlyAccess',
        user_groups=[],
        normalized_access=normalized
    )
    
    assert result.allowed is True
    assert result.account_name == 'Production'
    assert result.approvers == ['approver@example.com']
    assert result.self_approve is False


def test_validate_access_group_membership(sample_access_config):
    """Test access validation for group membership"""
    normalized = normalize_access_list(sample_access_config)
    
    result = validate_access(
        user_email='newuser@example.com',
        account_id='123456789012',
        permission_set='ReadOnlyAccess',
        user_groups=['developers'],
        normalized_access=normalized
    )
    
    assert result.allowed is True
    assert 'Group membership' in result.reason


def test_validate_access_self_approval(sample_access_config):
    """Test access validation for self-approval"""
    normalized = normalize_access_list(sample_access_config)
    
    result = validate_access(
        user_email='senior1@example.com',
        account_id='123456789012',
        permission_set='DeveloperAccess',
        user_groups=['pseudo:senior-engineers'],
        normalized_access=normalized
    )
    
    assert result.allowed is True
    assert result.self_approve is True
    assert len(result.approvers) == 0


def test_validate_access_denied_no_match(sample_access_config):
    """Test access validation denied for no matching policy"""
    normalized = normalize_access_list(sample_access_config)
    
    result = validate_access(
        user_email='unauthorized@example.com',
        account_id='123456789012',
        permission_set='ReadOnlyAccess',
        user_groups=[],
        normalized_access=normalized
    )
    
    assert result.allowed is False
    assert 'No matching access policy' in result.reason


def test_validate_access_invalid_account(sample_access_config):
    """Test access validation for non-existent account"""
    normalized = normalize_access_list(sample_access_config)
    
    result = validate_access(
        user_email='user@example.com',
        account_id='999999999999',
        permission_set='ReadOnlyAccess',
        user_groups=[],
        normalized_access=normalized
    )
    
    assert result.allowed is False
    assert 'not found in access list' in result.reason


def test_validate_access_invalid_permission_set(sample_access_config):
    """Test access validation for non-existent permission set"""
    normalized = normalize_access_list(sample_access_config)
    
    result = validate_access(
        user_email='user@example.com',
        account_id='123456789012',
        permission_set='NonExistentPermissionSet',
        user_groups=[],
        normalized_access=normalized
    )
    
    assert result.allowed is False
    assert 'not configured' in result.reason


def test_get_account_options(sample_access_config):
    """Test getting account options for dropdown"""
    normalized = normalize_access_list(sample_access_config)
    
    accounts = get_account_options(normalized)
    
    assert len(accounts) == 2
    assert accounts[0]['id'] in ['123456789012', '210987654321']
    assert accounts[0]['name'] in ['Production', 'Staging']
    
    # Check sorting by name
    names = [acc['name'] for acc in accounts]
    assert names == sorted(names)


def test_get_permission_set_options(sample_access_config):
    """Test getting permission set options for account"""
    normalized = normalize_access_list(sample_access_config)
    
    psets = get_permission_set_options('123456789012', normalized)
    
    assert 'ReadOnlyAccess' in psets
    assert 'DeveloperAccess' in psets
    assert len(psets) == 2
    
    # Check sorting
    assert psets == sorted(psets)


def test_get_permission_set_options_invalid_account(sample_access_config):
    """Test getting permission sets for non-existent account"""
    normalized = normalize_access_list(sample_access_config)
    
    psets = get_permission_set_options('999999999999', normalized)
    
    assert psets == []
