"""
Access normalizer with caching for efficient access validation

Transforms the hierarchical access list JSON into a flat lookup structure
for O(1) access validation. Expands pseudo-groups into user lists.

Cached at module level for performance across warm Lambda invocations.
"""

from typing import Dict, List, Set, Optional, Tuple
from aws_lambda_powertools import Logger

logger = Logger(child=True)

# Module-level cache
_normalized_access: Optional[Dict] = None
_pseudo_groups_cache: Optional[Dict[str, List[str]]] = None


class AccessValidationResult:
    """Result of access validation"""
    
    def __init__(
        self,
        allowed: bool,
        account_name: str = '',
        approvers: List[str] = None,
        self_approve: bool = False,
        reason: str = ''
    ):
        self.allowed = allowed
        self.account_name = account_name
        self.approvers = approvers or []
        self.self_approve = self_approve
        self.reason = reason


def normalize_access_list(access_list_config: Dict) -> Dict:
    """
    Transform access list into normalized lookup structure with caching
    
    Structure:
    {
        'account_id': {
            'account_name': 'Production',
            'permission_sets': {
                'PermissionSetName': {
                    'allowed_users': ['user1@example.com', ...],
                    'allowed_groups': ['group1', ...],
                    'approvers': ['approver@example.com', ...],
                    'self_approve': False
                }
            }
        }
    }
    
    Args:
        access_list_config: Raw access list from Secrets Manager
    
    Returns:
        Normalized access dictionary
    """
    global _normalized_access, _pseudo_groups_cache
    
    if _normalized_access is not None:
        logger.debug("Using cached normalized access list")
        return _normalized_access
    
    logger.info("Normalizing access list")
    
    # Cache pseudo-groups for group membership expansion
    _pseudo_groups_cache = access_list_config.get('pseudo_groups', {})

    for pg_name in _pseudo_groups_cache.keys():
        if not pg_name.startswith('pseudo:'):
            logger.error(f"Pseudo-group must start with 'pseudo:': {pg_name}")
            raise ValueError(f"Invalid pseudo-group name: {pg_name}")

    normalized = {}
    access_list = access_list_config.get('access_list', {})
    accounts = access_list.get('accounts', [])
    
    for account in accounts:
        account_id = account['id']
        account_name = account['name']
        
        normalized[account_id] = {
            'account_name': account_name,
            'permission_sets': {}
        }
        
        for pset in account.get('permission_sets', []):
            pset_name = pset['name']
            users = pset.get('users', [])
            groups = pset.get('groups', [])
            approvers = pset.get('approvers', [])
            
            # Expand pseudo-groups in the groups list
            expanded_groups = []
            pseudo_group_refs = []
            for group in groups:
                if group in _pseudo_groups_cache:
                    # This is a pseudo-group reference
                    pseudo_group_refs.append(group)
                    logger.debug(f"Found pseudo-group reference: {group}")
                else:
                    # This is a real Identity Center group
                    expanded_groups.append(group)
            
            normalized[account_id]['permission_sets'][pset_name] = {
                'allowed_users': set(users),
                'allowed_groups': set(expanded_groups),
                'allowed_pseudo_groups': set(pseudo_group_refs),
                'approvers': approvers,
                'self_approve': len(approvers) == 0,
            }
    
    _normalized_access = normalized
    
    logger.info("Access list normalized", extra={
        'accounts': len(normalized),
        'pseudo_groups': len(_pseudo_groups_cache)
    })
    
    return _normalized_access


def is_user_in_pseudo_group(user_email: str, group_name: str) -> bool:
    """
    Check if user is member of a pseudo-group
    
    Args:
        user_email: User's email address
        group_name: Pseudo-group name
    
    Returns:
        True if user is in the pseudo-group
    """
    if _pseudo_groups_cache is None:
        return False
    
    group_members = _pseudo_groups_cache.get(group_name, [])
    return user_email in group_members


def get_user_pseudo_groups(user_email: str) -> Set[str]:
    """
    Get all pseudo-groups a user belongs to
    
    Args:
        user_email: User's email address
    
    Returns:
        Set of pseudo-group names
    """
    if _pseudo_groups_cache is None:
        return set()
    
    user_groups = set()
    for group_name, members in _pseudo_groups_cache.items():
        if user_email in members:
            user_groups.add(group_name)
    
    return user_groups


def validate_access(
    user_email: str,
    account_id: str,
    permission_set: str,
    user_groups: List[str],
    normalized_access: Optional[Dict] = None
) -> AccessValidationResult:
    """
    Validate if user has access to account + permission set
    
    Checks in order:
    1. Direct user assignment
    2. Identity Center group membership
    3. Pseudo-group membership
    
    Args:
        user_email: User's email address
        account_id: AWS account ID
        permission_set: Permission set name
        user_groups: List of Identity Center groups user belongs to
        normalized_access: Pre-normalized access dict (optional, will load if not provided)
    
    Returns:
        AccessValidationResult with validation outcome
    """
    if normalized_access is None:
        # This shouldn't happen if called properly, but handle gracefully
        logger.warning("validate_access called without normalized_access")
        return AccessValidationResult(
            allowed=False,
            reason="Access list not loaded"
        )
    
    # Check if account exists
    if account_id not in normalized_access:
        return AccessValidationResult(
            allowed=False,
            reason=f"Account {account_id} not found in access list"
        )
    
    account_data = normalized_access[account_id]
    account_name = account_data['account_name']
    
    # Check if permission set exists for this account
    if permission_set not in account_data['permission_sets']:
        return AccessValidationResult(
            allowed=False,
            account_name=account_name,
            reason=f"Permission set {permission_set} not configured for {account_name}"
        )
    
    perm_set_data = account_data['permission_sets'][permission_set]
    
    # Check direct user assignment
    if user_email in perm_set_data['allowed_users']:
        logger.info("Access validated: direct user assignment", extra={
            'user': user_email,
            'account': account_name,
            'permission_set': permission_set
        })
        return AccessValidationResult(
            allowed=True,
            account_name=account_name,
            approvers=perm_set_data['approvers'],
            self_approve=perm_set_data['self_approve'],
            reason="Direct user assignment"
        )
    
    # Check Identity Center group membership
    user_group_set = set(user_groups)
    allowed_groups = perm_set_data['allowed_groups']
    
    if user_group_set & allowed_groups:  # Intersection check
        matching_groups = user_group_set & allowed_groups
        logger.info("Access validated: group membership", extra={
            'user': user_email,
            'account': account_name,
            'permission_set': permission_set,
            'groups': list(matching_groups)
        })
        return AccessValidationResult(
            allowed=True,
            account_name=account_name,
            approvers=perm_set_data['approvers'],
            self_approve=perm_set_data['self_approve'],
            reason=f"Group membership: {', '.join(matching_groups)}"
        )
    
    # Check pseudo-group membership
    user_pseudo_groups = get_user_pseudo_groups(user_email)
    matching_pseudo = user_pseudo_groups & perm_set_data['allowed_pseudo_groups']
    
    if matching_pseudo:
        logger.info("Access validated: pseudo-group membership", extra={
            'user': user_email,
            'account': account_name,
            'permission_set': permission_set,
            'pseudo_groups': list(matching_pseudo)
        })
        return AccessValidationResult(
            allowed=True,
            account_name=account_name,
            approvers=perm_set_data['approvers'],
            self_approve=perm_set_data['self_approve'],
            reason=f"Pseudo-group membership: {', '.join(matching_pseudo)}"
        )
    
    logger.warning("Access denied", extra={
        'user': user_email,
        'account': account_name,
        'permission_set': permission_set,
        'user_groups': user_groups,
        'user_pseudo_groups': list(user_pseudo_groups)
    })
    
    return AccessValidationResult(
        allowed=False,
        account_name=account_name,
        reason="No matching access policy found"
    )


def get_account_options(normalized_access: Dict) -> List[Dict[str, str]]:
    """
    Get list of accounts for Slack dropdown
    
    Args:
        normalized_access: Normalized access dictionary
    
    Returns:
        List of dicts with 'id', 'name' keys
    """
    accounts = []
    for account_id, data in normalized_access.items():
        accounts.append({
            'id': account_id,
            'name': data['account_name']
        })
    
    # Sort by name for better UX
    accounts.sort(key=lambda x: x['name'])
    return accounts


def get_permission_set_options(
    account_id: str,
    normalized_access: Dict
) -> List[str]:
    """
    Get list of permission sets for an account
    
    Args:
        account_id: AWS account ID
        normalized_access: Normalized access dictionary
    
    Returns:
        List of permission set names
    """
    if account_id not in normalized_access:
        return []
    
    psets = list(normalized_access[account_id]['permission_sets'].keys())
    psets.sort()  # Sort alphabetically
    return psets


def clear_cache() -> None:
    """Clear normalized access cache (useful for testing)"""
    global _normalized_access, _pseudo_groups_cache
    _normalized_access = None
    _pseudo_groups_cache = None
    logger.debug("Access normalizer cache cleared")
