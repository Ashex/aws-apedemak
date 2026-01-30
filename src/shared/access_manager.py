"""
Access manager for assigning/revoking access in identity center


"""

from typing import Dict
import boto3
from aws_lambda_powertools import Logger, Tracer

logger = Logger(child=True)
tracer = Tracer()


class AccessManager:
    """Manager for identity center access operations"""

    def __init__(self, identity_center_instance_arn: str):
        """
        Initialize Identity Center client

        Args:
            identity_center_instance_arn: ARN of the Identity Center instance
        """
        self.client = boto3.client('sso-admin')
        self.instance_arn = identity_center_instance_arn
        logger.info("AccessManager initialized", extra={'instance_arn': identity_center_instance_arn})

    @tracer.capture_method
    def assign_access(
            self,
            user_id: str,
            permission_set_arn: str,
            target_id: str,
    ) -> Dict:
        """
        Assign access to a user in Identity Center

        Args:
            user_id: User ID in Identity Center
            permission_set_arn: ARN of the permission set to assign
            target_id: Target ID (e.g., AWS account ID)

        Returns:
            Response from the assign operation
        """
        response = self.client.create_account_assignment(
            InstanceArn=self.instance_arn,
            TargetId=target_id,
            TargetType='AWS_ACCOUNT',
            PermissionSetArn=permission_set_arn,
            PrincipalType='USER',
            PrincipalId=user_id
        )
        if response['AccountAssignmentCreationStatus']['Status'] == 'SUCCEEDED':
            logger.info("Access assigned", extra={'user_id': user_id,
                                                  'permission_set_arn': permission_set_arn, 'target_id': target_id})
        elif response['AccountAssignmentCreationStatus']['Status'] == 'FAILED':
            logger.error("Failed to assign access", extra={'user_id': user_id,
                                                           'permission_set_arn': permission_set_arn,
                                                           'target_id': target_id,
                                                           'request_id': response['AccountAssignmentCreationStatus'][
                                                               'RequestId']})
            raise Exception("Failed to assign access")

    def revoke_access(
            self,
            user_id: str,
            permission_set_arn: str,
            target_id: str,
    ) -> Dict:
        """
        Revoke access from a user in Identity Center

        Args:
            user_id: User ID in Identity Center
            permission_set_arn: ARN of the permission set to revoke
            target_id: Target ID (e.g., AWS account ID)
        """

        response = self.client.delete_account_assignment(
            InstanceArn=self.instance_arn,
            TargetId=target_id,
            TargetType='AWS_ACCOUNT',
            PermissionSetArn=permission_set_arn,
            PrincipalType='USER',
            PrincipalId=user_id
        )
        if response['AccountAssignmentDeletionStatus']['Status'] == 'SUCCEEDED':
            logger.info("Access revoked", extra={'user_id': user_id,
                                                 'permission_set_arn': permission_set_arn, 'target_id': target_id})
        elif response['AccountAssignmentDeletionStatus']['Status'] == 'FAILED':
            logger.error("Failed to revoke access", extra={'user_id': user_id,
                                                           'permission_set_arn': permission_set_arn,
                                                           'target_id': target_id,
                                                           'request_id': response['AccountAssignmentDeletionStatus'][
                                                               'RequestId']})
            raise Exception("Failed to revoke")
