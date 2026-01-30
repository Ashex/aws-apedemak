# Slack App Setup Guide

This guide walks you through configuring a Slack app for Apedemak.

## Prerequisites

- Slack workspace with admin permissions
- Apedemak deployed to AWS (you'll need the API Gateway URL)

## Step 1: Create Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"**
3. Choose **"From scratch"**
4. Enter app name: **"Apedemak"** (or your preferred name)
5. Select your workspace
6. Click **"Create App"**

## Step 2: Configure OAuth Scopes

1. In the left sidebar, click **"OAuth & Permissions"**
2. Scroll to **"Bot Token Scopes"**
3. Add the following scopes:

   | Scope | Purpose |
   |-------|---------|
   | `chat:write` | Post messages to channels |
   | `users:read` | Read user information |
   | `users:read.email` | Read user email addresses for Identity Center mapping |
   | `commands` | Enable slash commands (future feature) |

4. Click **"Save Changes"**

## Step 3: Enable Interactivity

1. In the left sidebar, click **"Interactivity & Shortcuts"**
2. Toggle **"Interactivity"** to **ON**
3. Set **Request URL** to your API Gateway endpoint:
   ```
   https://your-api-id.execute-api.us-east-1.amazonaws.com/prod/slack/events
   ```
   (Get this from CDK deployment outputs or AWS Console)

4. Click **"Save Changes"**

## Step 4: Create Message Shortcut

Message shortcuts appear in the message context menu (⋮ on messages).

1. Still in **"Interactivity & Shortcuts"** page
2. Scroll to **"Shortcuts"** section
3. Click **"Create New Shortcut"**
4. Select **"On messages"** (important: not global shortcut)
5. Fill in the form:
   - **Name**: `Request Access`
   - **Short Description**: `Request AWS Identity Center access`
   - **Callback ID**: `request_access` (must match exactly)
6. Click **"Create"**

### How Users Trigger the Modal

In your dedicated Slack channel:
1. Hover over any message
2. Click the **⋮** (more actions) menu
3. Select **"Request Access"** from shortcuts
4. Modal appears with access request form

## Step 5: Install App to Workspace

1. In the left sidebar, click **"Install App"**
2. Click **"Install to Workspace"**
3. Review permissions and click **"Allow"**
4. Copy the **"Bot User OAuth Token"** (starts with `xoxb-`)
   - Save this securely - you'll need it for AWS Secrets Manager

## Step 6: Get Signing Secret

1. In the left sidebar, click **"Basic Information"**
2. Scroll to **"App Credentials"**
3. Copy the **"Signing Secret"**
   - Save this securely - you'll need it for AWS Secrets Manager

## Step 7: Store Credentials in AWS Secrets Manager

```bash
aws secretsmanager create-secret \
  --name apedemak/slack-credentials \
  --description "Slack app credentials for Apedemak" \
  --secret-string '{
    "bot_token": "xoxb-your-bot-token-here",
    "signing_secret": "your-signing-secret-here"
  }' \
  --region us-east-1
```

Or using AWS Console:
1. Go to AWS Secrets Manager
2. Click **"Store a new secret"**
3. Select **"Other type of secret"**
4. Add two key-value pairs:
   - Key: `bot_token`, Value: `xoxb-...`
   - Key: `signing_secret`, Value: `...`
5. Name: `apedemak/slack-credentials`
6. Click **"Store"**

## Step 8: Add Bot to Channel

1. Go to your Slack workspace
2. Navigate to the channel where you want access requests (e.g., `#aws-access-requests`)
3. Click channel name → **"Integrations"** → **"Add an App"**
4. Search for your app name and click **"Add"**

## Step 9: Test the Integration

1. In your configured channel, hover over any message
2. Click ⋮ → **"Request Access"**
3. Modal should appear with account/permission set options
4. Fill out the form and submit
5. Check Lambda logs if issues occur:
   ```bash
   aws logs tail /aws/lambda/apedemak-slack-handler --follow
   ```

## Troubleshooting

### Modal Doesn't Open

**Symptoms**: Nothing happens when clicking "Request Access"

**Solutions**:
1. Check API Gateway URL is correct in Interactivity settings
2. Verify Lambda has permission to read Secrets Manager
3. Check CloudWatch logs for signature verification errors:
   ```bash
   aws logs tail /aws/lambda/apedemak-slack-handler --follow
   ```
4. Ensure Callback ID is exactly `request_access`

### "Invalid Signature" Errors

**Symptoms**: 401 errors in CloudWatch logs

**Solutions**:
1. Verify signing secret in Secrets Manager matches Slack app
2. Check for leading/trailing spaces in secret values
3. Ensure timestamp tolerance (5 minutes) isn't exceeded

### "User Not Found in Identity Center"

**Symptoms**: Error when submitting access request

**Solutions**:
1. Verify user's Slack email matches Identity Center username
2. Check `users:read.email` scope is granted
3. Confirm user exists in Identity Center with correct email

### Bot Can't Post Messages

**Symptoms**: Approval messages don't appear

**Solutions**:
1. Verify bot is added to the channel
2. Check `chat:write` scope is granted
3. Ensure `SLACK_CHANNEL_ID` environment variable matches channel ID (not name)

### Getting Channel ID

Channel IDs look like `C0123456789`:

1. Right-click channel name → **"View channel details"**
2. Scroll to bottom, copy the **Channel ID**
3. Update `slackChannel` in `lib/config/default.config.ts`

## Modal Example

When triggered, the user sees:

![Modal Preview]

```
┌─────────────────────────────────────┐
│ Request Access                   × │
├─────────────────────────────────────┤
│ Context from message:               │
│ > Need to debug prod issue...       │
├─────────────────────────────────────┤
│ AWS Account                         │
│ [ Production ▼ ]                    │
│                                     │
│ Permission Set                      │
│ [ DeveloperAccess ]                 │
│                                     │
│ Duration                            │
│ ( ) 30 minutes                      │
│ (•) 1 hour                          │
│ ( ) 4 hours                         │
│ ( ) 8 hours                         │
│                                     │
│ Justification                       │
│ ┌─────────────────────────────────┐ │
│ │ Investigating production issue  │ │
│ │ #1234 - high severity bug       │ │
│ └─────────────────────────────────┘ │
│                                     │
│        [Cancel]  [Submit Request]   │
└─────────────────────────────────────┘
```

## Approval Message Example

After submission (if approval required):

```
🔐 Access Request

Requester:        @john.doe
Account:          Production
Permission Set:   DeveloperAccess
Duration:         4 hours

Justification:
Investigating production issue #1234 - high severity bug

Approvers: @team.lead @manager
                              [✅ Approve]

                [❌ Deny]
```

## Security Considerations

- **Signing Secret**: Never commit to version control
- **Bot Token**: Treat as highly sensitive (can post as bot)
- **Scope Minimization**: Only grant required OAuth scopes
- **Channel Restrictions**: Consider private channel for sensitive access requests
- **Audit Trail**: All actions logged to CloudWatch for compliance

## Advanced Configuration

### Custom Modal Branding

Edit `src/shared/messaging_adapter.py`:
```python
def create_access_request_modal(self, ...):
    # Customize modal title, labels, placeholder text
    return {
        "title": {"type": "plain_text", "text": "Your Custom Title"},
        ...
    }
```

### Adding Slash Commands

Future feature - add slash command for quick requests:

1. In Slack app settings, go to **"Slash Commands"**
2. Click **"Create New Command"**
3. Command: `/access-request`
4. Request URL: Same as interactivity URL
5. Update Lambda handler to process `command` payload type

### Rate Limiting

Slack enforces rate limits:
- 1 request per second per method
- Burst up to 100 requests

API Gateway throttling is configured to respect these limits.

## Support

If you encounter issues:

1. Check CloudWatch logs: `/aws/lambda/apedemak-slack-handler`
2. Enable debug logging: Set `LOG_LEVEL=DEBUG` in Lambda
3. Test signature verification with Slack's testing tools
4. Review [Slack API documentation](https://api.slack.com/docs)

## Next Steps

- Configure access list in `lib/config/default.config.ts`
- Set up approver notifications
- Test complete flow from request to approval
- Enable dry-run mode for safe testing
