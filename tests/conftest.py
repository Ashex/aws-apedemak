"""
Pytest configuration and fixtures
"""

import pytest
import boto3
from moto import mock_aws
import json


@pytest.fixture
def aws_credentials(monkeypatch):
    """Mock AWS credentials for testing"""
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'testing')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'testing')
    monkeypatch.setenv('AWS_SECURITY_TOKEN', 'testing')
    monkeypatch.setenv('AWS_SESSION_TOKEN', 'testing')
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')


@pytest.fixture
def sample_access_config():
    """Sample access configuration for testing"""
    return {
        'access_list': {
            'accounts': [
                {
                    'id': '123456789012',
                    'name': 'Production',
                    'permission_sets': [
                        {
                            'name': 'ReadOnlyAccess',
                            'users': ['user@example.com'],
                            'groups': ['developers'],
                            'approvers': ['approver@example.com']
                        },
                        {
                            'name': 'DeveloperAccess',
                            'users': [],
                            'groups': ['pseudo:senior-engineers'],
                            'approvers': []  # Self-approval
                        }
                    ]
                },
                {
                    'id': '210987654321',
                    'name': 'Staging',
                    'permission_sets': [
                        {
                            'name': 'DeveloperAccess',
                            'users': [],
                            'groups': ['developers'],
                            'approvers': []
                        }
                    ]
                }
            ]
        },
        'pseudo_groups': {
            'pseudo:senior-engineers': ['senior1@example.com', 'senior2@example.com']
        }
    }


@pytest.fixture
def mock_config(monkeypatch):
    """Mock environment variables for configuration"""
    monkeypatch.setenv('LEASES_TABLE_NAME', 'test-leases')
    monkeypatch.setenv('SLACK_SECRET_ARN', 'arn:aws:secretsmanager:us-east-1:123456789012:secret:test-slack')
    monkeypatch.setenv('ACCESS_LIST_SECRET_ARN', 'arn:aws:secretsmanager:us-east-1:123456789012:secret:test-access')
    monkeypatch.setenv('SLACK_CHANNEL_ID', 'C0123456789')
    monkeypatch.setenv('LOG_LEVEL', 'INFO')
    monkeypatch.setenv('DRY_RUN', 'false')
    monkeypatch.setenv('PERMISSION_DURATIONS', '[3600, 14400]')
    monkeypatch.setenv('REQUEST_EXPIRATION_SECONDS', '3600')
    monkeypatch.setenv('REMINDER_INTERVAL_SECONDS', '900')
    monkeypatch.setenv('REMINDER_BACKOFF', '1.5')
    monkeypatch.setenv('IDENTITY_CENTER_INSTANCE_ARN', 'arn:aws:sso:::instance/ssoins-test')
    monkeypatch.setenv('IDENTITY_STORE_ID', 'd-test123')
    monkeypatch.setenv('AUDIT_LOG_GROUP_SLACK', '/aws/lambda/test-slack-audit')
    monkeypatch.setenv('AUDIT_LOG_GROUP_REVOCATION', '/aws/lambda/test-revocation-audit')


@pytest.fixture
def dynamodb_table(aws_credentials):
    """Create mock DynamoDB table"""
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        
        table = dynamodb.create_table(
            TableName='test-leases',
            KeySchema=[
                {'AttributeName': 'lease_id', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'lease_id', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'},
                {'AttributeName': 'expires_at', 'AttributeType': 'N'},
                {'AttributeName': 'user_email', 'AttributeType': 'S'},
                {'AttributeName': 'created_at', 'AttributeType': 'N'}
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'ExpirationIndex',
                    'KeySchema': [
                        {'AttributeName': 'status', 'KeyType': 'HASH'},
                        {'AttributeName': 'expires_at', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                },
                {
                    'IndexName': 'UserIndex',
                    'KeySchema': [
                        {'AttributeName': 'user_email', 'KeyType': 'HASH'},
                        {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'},
                    'ProvisionedThroughput': {
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                }
            ],
            BillingMode='PROVISIONED',
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        
        yield table


@pytest.fixture
def secrets_manager(aws_credentials, sample_access_config):
    """Create mock Secrets Manager secrets"""
    with mock_aws():
        client = boto3.client('secretsmanager', region_name='us-east-1')
        
        # Slack credentials
        client.create_secret(
            Name='test-slack',
            SecretString=json.dumps({
                'bot_token': 'xoxb-test-token',
                'signing_secret': 'test-signing-secret'
            })
        )
        
        # Access list
        client.create_secret(
            Name='test-access',
            SecretString=json.dumps(sample_access_config)
        )
        
        yield client


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear module-level caches before each test"""
    from src.shared import config_loader, access_normalizer
    
    config_loader.clear_cache()
    access_normalizer.clear_cache()
    
    yield
    
    # Clear again after test
    config_loader.clear_cache()
    access_normalizer.clear_cache()
