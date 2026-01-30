"""
Identity Center mapper for AWS SSO operations

Provides a simplified interface for Identity Center account assignment operations
with user principal lookups via Identity Store.
"""

import boto3
from typing import List, Dict, Optional
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger

logger = Logger(child=True)

_org_accounts_cache: Optional[Dict[str, str]] = None  # {account_name: account_id}


class IdentityCenterMapper:
    """Wrapper for AWS Identity Center operations"""
    
    def __init__(self, instance_arn: str, identity_store_id: str):
        """
        Initialize Identity Center clients
        
        Args:
            instance_arn: SSO instance ARN
            identity_store_id: Identity Store ID
        """
        self.instance_arn = instance_arn
        self.identity_store_id = identity_store_id
        self.sso_admin = boto3.client('sso-admin')
        self.identity_store = boto3.client('identitystore')
        self.organisations = boto3.client('organizations')
    
    def get_user_principal_id(self, email: str) -> Optional[str]:
        """
        Get user principal ID from email address
        
        Args:
            email: User's email address
        
        Returns:
            User principal ID (UUID) or None if not found
        """
        try:
            response = self.identity_store.list_users(
                IdentityStoreId=self.identity_store_id,
                Filters=[
                    {
                        'AttributePath': 'UserName',
                        'AttributeValue': email
                    }
                ]
            )
            
            users = response.get('Users', [])
            if not users:
                # Try email attribute
                response = self.identity_store.list_users(
                    IdentityStoreId=self.identity_store_id,
                    Filters=[
                        {
                            'AttributePath': 'Emails.Value',
                            'AttributeValue': email
                        }
                    ]
                )
                users = response.get('Users', [])
            
            if users:
                user_id = users[0]['UserId']
                logger.info("Found user principal", extra={
                    'email': email,
                    'user_id': user_id
                })
                return user_id
            
            logger.warning("User not found in Identity Store", extra={'email': email})
            return None
            
        except ClientError as e:
            logger.error("Failed to lookup user", extra={
                'email': email,
                'error': str(e)
            })
            raise

    def get_user_groups(self, user_id: str) -> List[str]:
        """
        Get list of groups a user belongs to
        
        Args:
            user_id: User principal ID
        
        Returns:
            List of group display names
        """
        try:
            groups = []
            paginator = self.identity_store.get_paginator('list_group_memberships_for_member')
            
            for page in paginator.paginate(
                IdentityStoreId=self.identity_store_id,
                MemberId={'UserId': user_id}
            ):
                for membership in page.get('GroupMemberships', []):
                    group_id = membership['GroupId']
                    
                    # Get group details
                    group_response = self.identity_store.describe_group(
                        IdentityStoreId=self.identity_store_id,
                        GroupId=group_id
                    )
                    
                    group_name = group_response.get('DisplayName', '')
                    if group_name:
                        groups.append(group_name)
            
            logger.info("Retrieved user groups", extra={
                'user_id': user_id,
                'groups': groups
            })
            return groups
            
        except ClientError as e:
            logger.error("Failed to get user groups", extra={
                'user_id': user_id,
                'error': str(e)
            })
            raise

    def get_cached_accounts(self) -> Dict[str, str]:
        """
        Get organization accounts

        Returns:
            Dict mapping account name to account ID
        """
        global _org_accounts_cache

        if _org_accounts_cache is not None:
            logger.debug("Using cached organization accounts")
            return _org_accounts_cache

        logger.info("Caching organization accounts")
        accounts = {}

        try:
            paginator = self.organisations.get_paginator('list_accounts')
            for page in paginator.paginate():
                for account in page.get('Accounts', []):
                    name = account.get('Name')
                    account_id = account.get('Id')
                    if name and account_id:
                        accounts[name] = account_id

            _org_accounts_cache = accounts

            logger.info("Organization accounts cached", extra={
                'count': len(accounts)
            })

            return _org_accounts_cache

        except ClientError as e:
            logger.error("Failed to cache organization accounts", extra={
                'error': str(e)
            })
            raise

    def get_account_id(self, account_name: str) -> Optional[str]:
        """
        Get AWS account ID by account name

        Args:
            account_name: AWS account name

        Returns:
            AWS account ID or None if not found
        """
        accounts = self.get_cached_accounts()
        account_id = accounts.get(account_name)

        if account_id:
            logger.info("Found AWS account", extra={
                'name': account_name,
                'id': account_id
            })
        else:
            logger.warning("AWS Account not found", extra={
                'name': account_name
            })

        return account_id

    def get_permission_set_arn(self, account_id: str, permission_set_name: str) -> Optional[str]:
        """
        Get permission set ARN by name for an account
        
        Args:
            account_id: AWS account ID
            permission_set_name: Permission set name
        
        Returns:
            Permission set ARN or None if not found
        """
        try:
            paginator = self.sso_admin.get_paginator('list_permission_sets')
            
            for page in paginator.paginate(InstanceArn=self.instance_arn):
                for ps_arn in page.get('PermissionSets', []):
                    response = self.sso_admin.describe_permission_set(
                        InstanceArn=self.instance_arn,
                        PermissionSetArn=ps_arn
                    )
                    
                    ps_name = response['PermissionSet'].get('Name', '')
                    if ps_name == permission_set_name:
                        logger.info("Found permission set", extra={
                            'name': permission_set_name,
                            'arn': ps_arn
                        })
                        return ps_arn
            
            logger.warning("Permission set not found", extra={
                'name': permission_set_name,
                'account': account_id
            })
            return None
            
        except ClientError as e:
            logger.error("Failed to lookup permission set", extra={
                'name': permission_set_name,
                'error': str(e)
            })
            raise
    
    def create_account_assignment(
        self,
        account_id: str,
        permission_set_arn: str,
        principal_id: str,
        principal_type: str = 'USER'
    ) -> Dict:
        """
        Create account assignment (grant access)
        
        Args:
            account_id: AWS account ID
            permission_set_arn: Permission set ARN
            principal_id: User or group principal ID
            principal_type: 'USER' or 'GROUP'
        
        Returns:
            API response with request status
        """
        try:
            response = self.sso_admin.create_account_assignment(
                InstanceArn=self.instance_arn,
                TargetId=account_id,
                TargetType='AWS_ACCOUNT',
                PermissionSetArn=permission_set_arn,
                PrincipalType=principal_type,
                PrincipalId=principal_id
            )
            
            logger.info("Account assignment created", extra={
                'account_id': account_id,
                'principal_id': principal_id,
                'permission_set_arn': permission_set_arn,
                'status': response['AccountAssignmentCreationStatus']['Status']
            })
            
            return response
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            # Handle already exists case gracefully
            if error_code == 'ConflictException':
                logger.warning("Account assignment already exists", extra={
                    'account_id': account_id,
                    'principal_id': principal_id
                })
                return {'Status': 'ALREADY_EXISTS'}
            
            logger.error("Failed to create account assignment", extra={
                'account_id': account_id,
                'principal_id': principal_id,
                'error': str(e)
            })
            raise
    
    def delete_account_assignment(
        self,
        account_id: str,
        permission_set_arn: str,
        principal_id: str,
        principal_type: str = 'USER'
    ) -> Dict:
        """
        Delete account assignment (revoke access)
        
        Args:
            account_id: AWS account ID
            permission_set_arn: Permission set ARN
            principal_id: User or group principal ID
            principal_type: 'USER' or 'GROUP'
        
        Returns:
            API response with request status
        """
        try:
            response = self.sso_admin.delete_account_assignment(
                InstanceArn=self.instance_arn,
                TargetId=account_id,
                TargetType='AWS_ACCOUNT',
                PermissionSetArn=permission_set_arn,
                PrincipalType=principal_type,
                PrincipalId=principal_id
            )
            
            logger.info("Account assignment deleted", extra={
                'account_id': account_id,
                'principal_id': principal_id,
                'permission_set_arn': permission_set_arn,
                'status': response['AccountAssignmentDeletionStatus']['Status']
            })
            
            return response
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            # Handle not found case gracefully
            if error_code == 'ResourceNotFoundException':
                logger.warning("Account assignment not found (already deleted)", extra={
                    'account_id': account_id,
                    'principal_id': principal_id
                })
                return {'Status': 'NOT_FOUND'}
            
            logger.error("Failed to delete account assignment", extra={
                'account_id': account_id,
                'principal_id': principal_id,
                'error': str(e)
            })
            raise
    
    def list_account_assignments(
        self,
        account_id: str,
        permission_set_arn: str
    ) -> List[Dict]:
        """
        List all assignments for an account and permission set
        
        Args:
            account_id: AWS account ID
            permission_set_arn: Permission set ARN
        
        Returns:
            List of assignments with PrincipalId and PrincipalType
        """
        try:
            assignments = []
            paginator = self.sso_admin.get_paginator('list_account_assignments')
            
            for page in paginator.paginate(
                InstanceArn=self.instance_arn,
                AccountId=account_id,
                PermissionSetArn=permission_set_arn
            ):
                assignments.extend(page.get('AccountAssignments', []))
            
            logger.info("Listed account assignments", extra={
                'account_id': account_id,
                'count': len(assignments)
            })
            
            return assignments
            
        except ClientError as e:
            logger.error("Failed to list account assignments", extra={
                'account_id': account_id,
                'error': str(e)
            })
            raise
