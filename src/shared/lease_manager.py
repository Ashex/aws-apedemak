"""
Lease manager for DynamoDB operations

Handles CRUD operations for access leases with GSI queries for expiration
and user history lookups.
"""

import time
import uuid
from typing import Dict, List, Optional
import boto3
from boto3.dynamodb.conditions import Key, Attr
from aws_lambda_powertools import Logger, Tracer

logger = Logger(child=True)
tracer = Tracer()


class LeaseManager:
    """Manager for access lease DynamoDB operations"""
    
    def __init__(self, table_name: str):
        """
        Initialize DynamoDB table resource
        
        Args:
            table_name: DynamoDB table name
        """
        dynamodb = boto3.resource('dynamodb')
        self.table = dynamodb.Table(table_name)
        self.table_name = table_name
        logger.info("LeaseManager initialized", extra={'table': table_name})
    
    @tracer.capture_method
    def create_lease(
        self,
        user_email: str,
        slack_user_id: str,
        account_id: str,
        account_name: str,
        permission_set: str,
        duration_seconds: int,
        justification: str,
        slack_channel_id: str,
        request_message_ts: str,
        actioned_by: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict:
        """
        Create a new access lease
        
        Args:
            user_email: User's email address
            slack_user_id: Slack user ID
            account_id: AWS account ID
            account_name: AWS account name (for display)
            permission_set: Permission set name
            duration_seconds: Lease duration in seconds
            justification: Request justification
            slack_channel_id: Slack channel ID where request was made
            request_message_ts: Slack message timestamp of request
            actioned_by: Email of person who approved/denied (None for self-approval)
            dry_run: Whether this is a dry-run lease
        
        Returns:
            Created lease item
        """
        lease_id = f"lease_{uuid.uuid4().hex[:12]}"
        current_time = int(time.time())
        expires_at = current_time + duration_seconds
        
        # TTL set to 7 days after expiration for audit retention
        ttl = expires_at + (7 * 24 * 3600)
        
        item = {
            'lease_id': lease_id,
            'user_email': user_email,
            'slack_user_id': slack_user_id,
            'account_id': account_id,
            'account_name': account_name,
            'permission_set': permission_set,
            'status': 'ACTIVE',
            'created_at': current_time,
            'assigned_at': current_time,
            'expires_at': expires_at,
            'duration_seconds': duration_seconds,
            'justification': justification,
            'slack_channel_id': slack_channel_id,
            'request_message_ts': request_message_ts,
            'actioned_by': actioned_by or 'SELF_APPROVED',
            'dry_run': dry_run,
            'ttl': ttl
        }
        
        self.table.put_item(Item=item)
        
        logger.info("Lease created", extra={
            'lease_id': lease_id,
            'user_email': user_email,
            'account': account_name,
            'permission_set': permission_set,
            'expires_at': expires_at,
            'dry_run': dry_run
        })
        
        return item
    
    @tracer.capture_method
    def get_lease(self, lease_id: str) -> Optional[Dict]:
        """
        Get lease by ID
        
        Args:
            lease_id: Lease ID
        
        Returns:
            Lease item or None if not found
        """
        response = self.table.get_item(Key={'lease_id': lease_id})
        
        if 'Item' in response:
            return response['Item']
        
        logger.warning("Lease not found", extra={'lease_id': lease_id})
        return None
    
    @tracer.capture_method
    def get_expired_leases(self, limit: int = 100) -> List[Dict]:
        """
        Query expired leases using GSI
        
        Queries ExpirationIndex where status='ACTIVE' and expires_at < now
        
        Args:
            limit: Maximum number of leases to return
        
        Returns:
            List of expired lease items
        """
        current_time = int(time.time())
        
        try:
            response = self.table.query(
                IndexName='ExpirationIndex',
                KeyConditionExpression=Key('status').eq('ACTIVE') & Key('expires_at').lt(current_time),
                Limit=limit
            )
            
            leases = response.get('Items', [])
            
            logger.info("Queried expired leases", extra={
                'count': len(leases),
                'scanned': response.get('ScannedCount', 0)
            })
            
            return leases
            
        except Exception as e:
            logger.error("Failed to query expired leases", extra={'error': str(e)})
            raise
    
    @tracer.capture_method
    def get_user_leases(
        self,
        user_email: str,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get all leases for a user
        
        Queries UserIndex, returns most recent first
        
        Args:
            user_email: User's email address
            status: Filter by status (None for all)
            limit: Maximum number of leases to return
        
        Returns:
            List of lease items
        """
        try:
            query_kwargs = {
                'IndexName': 'UserIndex',
                'KeyConditionExpression': Key('user_email').eq(user_email),
                'ScanIndexForward': False,  # Descending order (newest first)
                'Limit': limit
            }
            
            if status:
                query_kwargs['FilterExpression'] = Attr('status').eq(status)
            
            response = self.table.query(**query_kwargs)
            leases = response.get('Items', [])
            
            logger.info("Queried user leases", extra={
                'user_email': user_email,
                'status': status,
                'count': len(leases)
            })
            
            return leases
            
        except Exception as e:
            logger.error("Failed to query user leases", extra={
                'user_email': user_email,
                'error': str(e)
            })
            raise
    
    @tracer.capture_method
    def update_lease_status(
        self,
        lease_id: str,
        status: str,
        revoked_at: Optional[int] = None,
        ttl: Optional[int] = None,
        actioned_by: Optional[str] = None,
    ) -> None:
        """
        Update lease status
        
        Args:
            lease_id: Lease ID
            status: New status (ACTIVE, EXPIRED, REVOKED)
            revoked_at: Timestamp of revocation (for REVOKED status)
            ttl: TTL timestamp for DynamoDB record expiration
            actioned_by: Email of person who approved/denied
        """
        update_expr = 'SET #status = :status'
        expr_names = {'#status': 'status'}
        expr_values = {':status': status}
        
        if revoked_at:
            update_expr += ', revoked_at = :revoked_at'
            expr_values[':revoked_at'] = revoked_at

        if ttl:
            update_expr += ', #ttl = :ttl'
            expr_names['#ttl'] = 'ttl'
            expr_values[':ttl'] = ttl

        if actioned_by:
            update_expr += ', actioned_by = :actioned_by'
            expr_values[':actioned_by'] = actioned_by

        self.table.update_item(
            Key={'lease_id': lease_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        
        logger.info("Lease status updated", extra={
            'lease_id': lease_id,
            'status': status
        })
    
    @tracer.capture_method
    def revoke_lease(self, lease_id: str) -> None:
        """
        Revoke an active lease before expiration
        Record will be retained for 14 days
        
        Args:
            lease_id: Lease ID
        """
        current_time = int(time.time())
        ttl = current_time + (14 * 24 * 3600)  # 14 days from now

        self.update_lease_status(
            lease_id=lease_id,
            status='REVOKED',
            revoked_at=int(time.time()),
            ttl=ttl
        )
        
        logger.info("Lease revoked", extra={'lease_id': lease_id})
    
    @tracer.capture_method
    def mark_lease_expired(self, lease_id: str) -> None:
        """
        Mark lease as expired
        
        Args:
            lease_id: Lease ID
        """
        self.update_lease_status(lease_id=lease_id, status='EXPIRED')
        logger.info("Lease marked as expired", extra={'lease_id': lease_id})
    
    @tracer.capture_method
    def get_lease_for_assignment(
        self,
        user_email: str,
        account_id: str,
        permission_set: str,
        status: Optional[str] = 'ACTIVE'
    ) -> Optional[Dict]:
        """
        Check if there's a lease for a specific assignment
        
        Args:
            user_email: User's email address
            account_id: AWS account ID
            permission_set: Permission set name
            status: Lease status to filter by (default 'ACTIVE')
        
        Returns:
            Active lease item or None
        """
        leases = self.get_user_leases(user_email=user_email, status=status)
        
        for lease in leases:
            if (lease['account_id'] == account_id and 
                lease['permission_set'] == permission_set):
                return lease
        
        return None
