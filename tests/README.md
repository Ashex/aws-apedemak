# Testing

This directory contains the test suite for Apedemak using pytest.

## Test Structure

```
tests/
├── conftest.py           # Shared fixtures and configuration
├── unit/                 # Unit tests for individual modules
│   ├── test_config_loader.py
│   ├── test_access_normalizer.py
│   ├── test_messaging_adapter.py
│   └── test_lease_manager.py
├── component/            # Component tests for Lambda handlers
│   ├── test_slack_handler.py
│   └── test_access_revocation.py
└── integration/          # Integration tests for complete journeys
    └── test_journeys.py
```

## Test Methodology

### Unit Tests
- Test individual functions and modules in isolation
- Mock all external dependencies (AWS services, Slack API)
- Focus on business logic correctness
- Fast execution (<1s per test)

### Component Tests
- Test Lambda handlers with mocked AWS services (using moto)
- Verify request/response handling
- Test error cases and edge conditions
- Moderate execution (~1-5s per test)

### Integration Tests
- Test complete user journeys end-to-end
- Use moto for AWS service mocking
- Simulate actual Slack payloads
- Comprehensive validation of workflows
- Slower execution (~5-30s per test)

## Running Tests

### Prerequisites

Install test dependencies:
```bash
pip install -e ".[dev]"
```

### Run All Tests

```bash
pytest
```

### Run Specific Test Categories

```bash
# Unit tests only
pytest tests/unit/

# Component tests only
pytest tests/component/

# Integration tests only
pytest tests/integration/

# Specific test file
pytest tests/unit/test_access_normalizer.py

# Specific test function
pytest tests/unit/test_access_normalizer.py::test_normalize_access_list
```

### Run with Coverage

```bash
pytest --cov=src --cov-report=html
```

View coverage report:
```bash
open htmlcov/index.html
```

### Run with Verbose Output

```bash
pytest -v
```

### Run Tests Matching Pattern

```bash
pytest -k "test_access"
```

## Test Coverage Goals

- **Unit tests**: >80% code coverage
- **Component tests**: All Lambda handler paths
- **Integration tests**: All 7 user journeys

## 7 Key User Journeys

1. **Incoming Access Request** - User opens modal and submits valid request
2. **Invalid Account/Permission** - Request for non-existent or unauthorized access
3. **Non-Existent Assignment** - Request for permission set not in Identity Center
4. **Access Request Approved** - Approver clicks approve, access granted
5. **Access Request Denied** - Approver clicks deny, no access granted
6. **Expired Lease Revocation** - Scheduled job revokes access after expiration
7. **Invalid Direct Assignment Cleanup** - Scheduled job detects and revokes unauthorized access

## Writing Tests

### Unit Test Example

```python
def test_normalize_access_list(sample_access_config):
    """Test access list normalization"""
    from src.shared.access_normalizer import normalize_access_list
    
    result = normalize_access_list(sample_access_config)
    
    assert '123456789012' in result
    assert result['123456789012']['account_name'] == 'Production'
    assert 'ReadOnlyAccess' in result['123456789012']['permission_sets']
```

### Component Test Example

```python
def test_slack_handler_modal_open(mock_config, secrets_manager, dynamodb_table):
    """Test opening access request modal"""
    from src.lambdas.slack_handler import handler
    
    event = {
        'body': json.dumps({
            'type': 'message_action',
            'trigger_id': 'test-trigger',
            'user': {'id': 'U123'},
            'message': {'text': 'test message'}
        }),
        'headers': {
            'x-slack-request-timestamp': str(int(time.time())),
            'x-slack-signature': 'v0=test-signature'
        }
    }
    
    response = handler.handler(event, {})
    
    assert response['statusCode'] == 200
```

### Integration Test Example

```python
def test_complete_access_request_flow(mock_config, secrets_manager, dynamodb_table):
    """Test complete flow from request to approval to revocation"""
    # 1. User requests access
    # 2. Approval message posted
    # 3. Approver approves
    # 4. Access granted
    # 5. Lease created
    # 6. Time passes
    # 7. Revocation job runs
    # 8. Access revoked
    pass
```

## Mocking Patterns

### AWS Services (using moto)

```python
from moto import mock_dynamodb, mock_secretsmanager

@mock_dynamodb
@mock_secretsmanager
def test_with_aws_mocks():
    # Test code here
    pass
```

### Slack API (using pytest-mock)

```python
def test_slack_interaction(mocker):
    mock_client = mocker.patch('slack_sdk.WebClient')
    mock_client.return_value.views_open.return_value = {'view': {'id': 'V123'}}
    
    # Test code here
```

## Debugging Tests

### Print Debugging

```bash
pytest -s  # Show print statements
```

### Drop into Debugger on Failure

```bash
pytest --pdb
```

### Run Last Failed Tests

```bash
pytest --lf
```

## Continuous Integration

Tests should run in CI/CD pipeline before deployment:

```bash
# In CI pipeline
pytest --cov=src --cov-report=xml --junitxml=test-results.xml
```

## Test Data

Test fixtures provide:
- Sample access configurations
- Mock AWS credentials
- DynamoDB tables with GSIs
- Secrets Manager secrets
- Slack payloads

All test data is isolated and cleaned up automatically.
