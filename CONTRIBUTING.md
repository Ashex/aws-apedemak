# Contributing to Apedemak

Thank you for your interest in contributing to Apedemak! This document provides an overview of the codebase structure, design philosophy, and development guidelines.

## Code Organization

### Shared Modules

### Module Responsibilities

**config_loader.py**
- Loads configuration from environment variables
- Fetches secrets from Secrets Manager
- Implements module-level caching for performance
- Single source of truth for configuration

**access_normalizer.py**
- Transforms hierarchical access list into flat lookup structure
- Expands pseudo-groups into user lists
- Provides fast O(1) access validation
- Separates policy definition from enforcement

**messaging/ (Hexagonal Architecture)**
- Implements port (interface) for messaging platforms
- Slack adapter provides concrete implementation
- Enables platform-agnostic Lambda handlers
- **Design Pattern**: Ports and Adapters (Hexagonal Architecture)

**identity_mapper.py**
- Wraps AWS Identity Center SDK operations
- Handles user principal lookups
- Manages account assignments (grant/revoke)
- Provides clean interface hiding API complexity

**lease_manager.py**
- DynamoDB CRUD operations for access leases
- GSI queries for expiration and user history
- Implements audit trail with TTL
- Single source of truth for lease state

## Messaging Interface

Apedemak abstracts the messaging logic into an interface so it can theoretically support any platform.

### Why This interface?

The application core defines what it needs (the interface) without knowing how it will be provided (the adapter). This:


### Interface

The interface (`messaging/interface.py`) defines the contract:

```python
from abc import ABC, abstractmethod

class MessagingInterface(ABC):
    @abstractmethod
    def verify_webhook_signature(self, body, timestamp, signature) -> bool:
        pass
    
    @abstractmethod
    def parse_webhook_event(self, body, headers) -> WebhookEvent:
        pass
    
    @abstractmethod
    def create_access_request_modal(self, payload: AccessRequestPayload) -> Dict:
        pass
    
    @abstractmethod
    def post_approval_message(self, payload: ApprovalMessagePayload) -> Dict:
        pass
    
    # ... other methods
```

### Slack Adapter Implementation

```python
class SlackMessagingAdapter(MessagingInterface):
    """Slack-specific implementation of MessagingPort"""
    
    def __init__(self, bot_token: str, signing_secret: str):
        self.client = WebClient(token=bot_token)
        self.signing_secret = signing_secret
    
    def verify_webhook_signature(self, body, timestamp, signature) -> bool:
        # Slack-specific HMAC verification
        sig_basestring = f"v0:{timestamp}:{body}"
        computed = hmac.new(self.signing_secret, sig_basestring, hashlib.sha256)
        return hmac.compare_digest(computed, signature)
    
    def parse_webhook_event(self, body, headers) -> WebhookEvent:
        # Parse Slack payload and convert to platform-agnostic WebhookEvent
        payload = json.loads(body)
        return WebhookEvent(
            event_type=WebhookEventType.MESSAGE_SHORTCUT,
            user_id=payload['user']['id'],
            # ... extract and normalize data
        )
```

### Example: Adding Microsoft Teams Support

```python
class TeamsMessagingAdapter(MessagingInterface):
    """Microsoft Teams implementation of MessagingPort"""
    
    def __init__(self, webhook_url: str, app_id: str, app_secret: str):
        self.webhook_url = webhook_url
        self.app_id = app_id
        self.app_secret = app_secret
    
    def verify_webhook_signature(self, body, timestamp, signature) -> bool:
        # Teams-specific JWT verification
        pass
    
    def parse_webhook_event(self, body, headers) -> WebhookEvent:
        # Parse Teams payload and convert to WebhookEvent
        payload = json.loads(body)
        return WebhookEvent(
            event_type=self._map_teams_event_type(payload['type']),
            user_id=payload['from']['id'],
            # ... Teams-specific extraction
        )
    
    def create_access_request_modal(self, payload: AccessRequestPayload) -> Dict:
        # Convert to Teams Adaptive Card format
        return {
            "type": "AdaptiveCard",
            "body": [...],
            "actions": [...]
        }
```

Then in the handler:
```python
# Configuration determines which adapter to use
if config['platform'] == 'slack':
    messaging = SlackMessagingAdapter(token, secret)
elif config['platform'] == 'teams':
    messaging = TeamsMessagingAdapter(webhook, app_id, secret)

# Handler code is identical regardless of platform
web event = messaging.parse_webhook_event(body, headers)
if event.event_type == WebhookEventType.MESSAGE_SHORTCUT:
    modal = messaging.create_access_request_modal(payload)
    messaging.open_modal(event.trigger_id, modal)
```

### Platform-Agnostic Data Classes

The interface defines shared data structures:

```python
@dataclass
class WebhookEvent:
    event_type: WebhookEventType
    user_id: str
    user_email: Optional[str]
    trigger_id: Optional[str]
    view_data: Optional[Dict]
    metadata: Optional[Dict]

@dataclass
class ApprovalMessagePayload:
    channel_id: str
    requester_id: str
    account_name: str
    permission_set: str
    duration_seconds: int
    approver_emails: List[str]
```

These ensure the handler never touches platform-specific formats.

## Development Workflow

### 1. Set Up Environment

```bash
# Install CDK dependencies
npm install

# Install Python dependencies
uv pip install -e ".[dev]"

# Activate virtual environment
source .venv/bin/activate
```

### 2. Run Tests

```bash
# Run all tests
pytest

# Run specific test category
pytest tests/unit/

# Run with coverage
pytest --cov=src --cov-report=html
```

### 3. Lint and Format

```bash
# Format Python code
black src/ tests/

# Lint Python code
ruff check src/ tests/

# Type check Python
mypy src/

# Format TypeScript
npm run build
```

### 4. Test Deployment

```bash
# Synthesize CloudFormation
npm run synth

# Check diff against deployed stack
npm run diff

# Deploy to dev environment
npm run deploy
```

### 6. Submit PR

- Include tests for new features
- Update documentation if needed
- Follow commit message conventions

## Testing Guidelines

### Test Pyramid

- **Unit tests** (most): Test individual functions, mock external services
- **Component tests** (moderate): Test Lambda handlers, use moto for AWS mocks
- **Integration tests** (few): Test complete user journeys end-to-end

### Writing Good Tests

```python
def test_feature_name():
    """Test that X does Y when Z"""
    # Arrange - Set up test data
    config = {...}
    
    # Act - Execute the code under test
    result = function_to_test(config)
    
    # Assert - Verify the outcome
    assert result == expected_value
```

### Mocking Best Practices

- Mock at the boundary (AWS SDK, Slack API)
- Don't mock your own code
- Use moto for AWS services
- Use pytest-mock for external APIs

## Code Style

### Python

- Follow PEP 8
- Use type hints for function signatures
- Maximum line length: 100 characters
- Docstrings for all public functions

```python
def create_lease(user_email: str, account_id: str) -> Dict[str, Any]:
    """
    Create a new access lease
    
    Args:
        user_email: User's email address
        account_id: AWS account ID
    
    Returns:
        Created lease item with lease_id
    """
```

## Debugging

### Local Testing

```bash
# Run specific Lambda handler locally
python -m src.lambdas.slack_handler.handler

# With environment variables
export LEASES_TABLE_NAME=test-table
python -m src.lambdas.slack_handler.handler
```

### CloudWatch Logs

```bash
# Tail logs for Slack handler
aws logs tail /aws/lambda/apedemak-slack-handler --follow

# Audit logs
aws logs tail /aws/lambda/apedemak-slack-handler-audit --follow
```

### X-Ray Traces

View traces in AWS X-Ray console to debug performance issues.

## Performance Considerations

### Lambda Cold Starts

- Python 3.12 with ARM64: ~500-800ms
- Shared module bundling: +100-200ms
- First Secrets Manager call: +100-200ms

**Optimization**: Module-level caching eliminates repeat costs

### Warm Start Performance

- Config cached: <5ms overhead
- Access validation: O(1) lookup
- DynamoDB queries: 10-50ms
- Identity Center API: 100-500ms

## Security

- **Never log secrets** - Use `POWERTOOLS_LOGGER_LOG_EVENT=false`
- **Verify Slack signatures** - Prevent unauthorized requests
- **Least privilege IAM** - Grant only required permissions
- **Audit logging** - All actions logged to dedicated log groups
- **Encryption** - Secrets Manager encrypts at rest

## Questions?

- Open an issue for bugs or feature requests
- Start a discussion for design questions
- Review existing code for patterns and examples

Thank you for contributing to Apedemak! 🚀
