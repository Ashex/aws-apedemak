# AWS Apedemak

Slack-based AWS Identity Center access request management system with temporary permission assignments.

## Overview

Apedemak provides a simple, secure way for teams to request and approve temporary AWS access through Slack. Platform engineers, developers, and architects can request elevated permissions for a specific duration, and designated approvers can grant access with a single click.

**Key Features:**
- 🔐 Temporary AWS access through Identity Center permission sets
- 💬 Native Slack workflow with message shortcuts
- ✅ Single-approver or self-approval patterns
- 👥 Support for user, group, and pseudo-group access policies
- 🧪 Dry-run mode for testing
- ⏱️ Automatic access revocation on expiration
- 📊 Complete audit logging to CloudWatch

## Architecture

- **Slack Handler Lambda**: Processes access requests, approvals, and modal interactions
- **Access Revocation Lambda**: Removes expired leases and invalid direct assignments (scheduled via EventBridge)
- **DynamoDB Table**: Stores active access leases with GSI for expiration queries
- **API Gateway**: Webhook endpoint for Slack events
- **Secrets Manager**: Stores Slack credentials and access list configuration

## Prerequisites

- AWS Account with Identity Center enabled
- Slack workspace with admin permissions
- Node.js 18+ and npm (for CDK)
- Python 3.13+ (for Lambda development)
- Docker (for Lambda bundling, or Python 3.13 locally as fallback)
- AWS CLI configured with appropriate credentials

## Quick Start

### 1. Install Dependencies

```bash
# Install CDK dependencies
npm install

# Install Python dependencies (for local development/testing)
pip install -e ".[dev]"
```

### 2. Configure Access List

Create your access configuration in `lib/config/default.config.ts`:

```typescript
export const accessListConfig: AccessListConfig = {
  accounts: [
    {
      id: '123456789012',
      name: 'Production',
      permissionSets: [
        {
          name: 'ReadOnlyAccess',
          users: ['user@example.com'],
          groups: ['developers'],
          approvers: ['lead@example.com']
        }
      ]
    }
  ],
  pseudoGroups: {
    'pseudo:principal-engineers': ['pe1@example.com', 'pe2@example.com']
  }
};
```

### 3. Deploy Infrastructure

```bash
# Synthesize CloudFormation template
npx cdk synth

# Deploy to AWS
npx cdk deploy
```

Note the API Gateway URL from the deployment outputs.

### 4. Configure Slack App

1. Create a new Slack app at [api.slack.com/apps](https://api.slack.com/apps)
2. Add the following OAuth scopes:
   - `chat:write`
   - `users:read`
   - `users:read.email`
   - `commands`
3. Enable Interactivity and set Request URL to: `https://<your-api-url>/slack/events`
4. Add a Message Shortcut:
   - Name: "Request Access"
   - Callback ID: `request_access`
5. Install app to your workspace
6. Store Slack credentials in AWS Secrets Manager:

```bash
aws secretsmanager create-secret \
  --name apedemak/slack-credentials \
  --secret-string '{
    "bot_token": "xoxb-your-bot-token",
    "signing_secret": "your-signing-secret"
  }'
```

### 5. Test the Workflow

1. In Slack, hover over any message in your designated request channel
2. Click the "More actions" (⋮) menu
3. Select "Request Access"
4. Fill out the modal with account, permission set, and duration
5. Approvers will be tagged to approve or deny the request

## Configuration

### Environment-Specific Settings

Edit `lib/config/default.config.ts` to customize:

- `permissionDurations`: Available duration options (in `hh:mm` format, e.g. `['00:30', '01:00', '04:00']`)
- `slackChannel`: Channel ID for access requests
- `logLevel`: Logging verbosity (INFO, DEBUG, WARNING, ERROR)
- `dryRunMode`: Enable/disable dry-run testing
- `requestExpirationSeconds`: How long approval requests remain valid
- `reminderIntervalSeconds`: Interval for approval reminders
- `reminderBackoff`: Backoff multiplier for reminders

### Access List Configuration

The access list defines who can request what:

- **accounts**: List of AWS accounts with permission sets
- **permissionSets**: Available permission sets per account
  - `name`: Permission set name (must exist in Identity Center)
  - `users`: Email addresses with direct access
  - `groups`: Identity Center group names
  - `approvers`: Users who can approve requests (empty for self-approval)
- **pseudoGroups**: Custom groups not in Identity Center (names must start with `pseudo:`, e.g., `pseudo:principal-engineers`)

## Access Patterns

### Direct User Assignment
```typescript
users: ['user@example.com']
```

### Group Membership
```typescript
groups: ['developers', 'platform-team']
```

### Pseudo-Group (Custom)
```typescript
// In pseudoGroups — names must start with 'pseudo:'
pseudoGroups: {
  'pseudo:senior-engineers': ['user1@example.com', 'user2@example.com']
}

// Reference in permission set groups list
groups: ['pseudo:senior-engineers']
```

### Self-Approval
```typescript
approvers: []  // Empty array enables self-approval
```

## Operations

### Monitoring

Access logs are written to CloudWatch Log Groups:
- `/aws/lambda/apedemak-slack-handler-audit`
- `/aws/lambda/apedemak-access-revocation-audit`

### Dry-Run Mode

Enable dry-run to test without making actual permission changes:

```typescript
export const apedemakConfig: ApedemakConfig = {
  // ...
  dryRunMode: true
};
```

In dry-run mode:
- Slack messages show "🧪 DRY-RUN MODE" indicator
- Access assignments are simulated (not created in Identity Center)
- Revocations are logged but not executed

### Troubleshooting

**Access requests fail validation:**
- Verify account ID and permission set name in access list
- Check user email matches Identity Center principal
- Confirm permission set exists in target account

**Modal doesn't open:**
- Verify Slack signing secret is correct
- Check API Gateway endpoint is accessible
- Review Lambda logs for signature verification errors

**Access not granted after approval:**
- Verify Lambda has `sso-admin` permissions
- Check Identity Center instance ARN in configuration
- Review audit logs for Identity Center API errors

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines and architecture details.

See [tests/README.md](tests/README.md) for testing methodology.

## Security

- All access requests are logged to CloudWatch for audit trails
- Slack signature verification prevents unauthorized requests
- IAM roles follow least-privilege principles
- Secrets stored in AWS Secrets Manager with encryption
- Access automatically revoked on expiration

## License

MIT
