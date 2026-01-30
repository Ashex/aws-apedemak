import { Stack, StackProps, CfnOutput, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import { NagSuppressions } from 'cdk-nag';
import { StorageConstruct } from './constructs/storage.construct';
import { SecretsConstruct } from './constructs/secrets.construct';
import { LambdaFunction } from './constructs/lambda-function.construct';
import { ApiConstruct } from './constructs/api.construct';
import { SchedulerConstruct } from './constructs/scheduler.construct';
import { AuditingConstruct } from './constructs/auditing.construct';
import { ApedemakConfig, AccessListConfig } from './config/config.interface';
import { mergeAccessConfig, calculateScheduleExpression } from './config/config-merger';

export interface ApedemakStackProps extends StackProps {
  /** Apedemak configuration */
  readonly config: ApedemakConfig;
  /** Access list configuration */
  readonly accessList: AccessListConfig;
}

/**
 * Main Apedemak CDK stack
 * 
 * Single-stack architecture for simplicity and maintainability
 */
export class ApedemakStack extends Stack {
  constructor(scope: Construct, id: string, props: ApedemakStackProps) {
    super(scope, id, props);

    const { config, accessList } = props;

    // Merge access configuration for Secrets Manager
    const mergedAccessConfig = mergeAccessConfig(accessList);

    // Parse hh:mm durations to seconds for schedule calculation
    const durationSeconds = config.permissionDurations.map(d => {
      const [hours, minutes] = d.split(':').map(Number);
      return hours * 3600 + minutes * 60;
    });
    const scheduleExpression = calculateScheduleExpression(durationSeconds);

    // Create monitoring resources (audit log groups)
    const monitoring = new AuditingConstruct(this, 'Monitoring');

    // Create storage layer (DynamoDB)
    const storage = new StorageConstruct(this, 'Storage');

    // Create secrets (Slack credentials + access list)
    const secrets = new SecretsConstruct(this, 'Secrets', {
      accessConfig: mergedAccessConfig,
    });

    // Common environment variables for Lambda functions
    const commonEnv = {
      LEASES_TABLE_NAME: storage.leasesTable.tableName,
      SLACK_SECRET_ARN: secrets.slackSecret.secretArn,
      ACCESS_LIST_SECRET_ARN: secrets.accessListSecret.secretArn,
      SLACK_CHANNEL_ID: config.slackChannel,
      LOG_LEVEL: config.logLevel,
      DRY_RUN: config.dryRunMode.toString(),
      PERMISSION_DURATIONS: JSON.stringify(
        config.permissionDurations.map(time => {
          const [hours, minutes] = time.split(':').map(Number);
          return hours * 3600 + minutes * 60;
        })
      ),
      REQUEST_EXPIRATION_SECONDS: config.requestExpirationSeconds.toString(),
      REMINDER_INTERVAL_SECONDS: config.reminderIntervalSeconds.toString(),
      REMINDER_BACKOFF: config.reminderBackoff.toString(),
      IDENTITY_CENTER_INSTANCE_ARN: config.identityCenterInstanceArn,
      IDENTITY_STORE_ID: config.identityStoreId,
      AUDIT_LOG_GROUP_MESSAGE: monitoring.messageAuditLogGroup.logGroupName,
      AUDIT_LOG_GROUP_REVOCATION: monitoring.revocationAuditLogGroup.logGroupName,
    };

    // Create Message handler Lambda
    const messageHandler = new LambdaFunction(this, 'MessageHandler', {
      functionName: 'apedemak-message-handler',
      codePath: 'src/lambdas/message_handler',
      handler: 'handler.handler',
      memorySize: 512,
      timeout: Duration.seconds(29), // Just under API Gateway timeout
      environment: commonEnv,
      provisionedConcurrency: 1,
    });

    // Create access revocation Lambda
    const revocationHandler = new LambdaFunction(this, 'RevocationHandler', {
      functionName: 'apedemak-access-revocation',
      codePath: 'src/lambdas/access_revocation',
      handler: 'handler.handler',
      memorySize: 512,
      timeout: Duration.seconds(300), // 5 minutes for processing many leases
      environment: commonEnv,
    });

    // Grant Lambda permissions

    // DynamoDB access
    storage.leasesTable.grantReadWriteData(messageHandler.function);
    storage.leasesTable.grantReadWriteData(revocationHandler.function);

    // Secrets Manager access
    secrets.slackSecret.grantRead(messageHandler.function);
    secrets.slackSecret.grantRead(revocationHandler.function);
    secrets.accessListSecret.grantRead(messageHandler.function);
    secrets.accessListSecret.grantRead(revocationHandler.function);

    // Audit logging permissions
    monitoring.messageAuditLogGroup.grantWrite(messageHandler.function);
    monitoring.revocationAuditLogGroup.grantWrite(revocationHandler.function);

    // Identity Center permissions for both Lambdas
    const identityCenterPolicy = new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'sso-admin:CreateAccountAssignment',
        'sso-admin:DeleteAccountAssignment',
        'sso-admin:ListAccountAssignments',
        'sso-admin:ListAccountAssignmentsForPrincipal',
        'sso-admin:DescribePermissionSet',
        'sso-admin:ListPermissionSets',
        'identitystore:ListUsers',
        'identitystore:DescribeUser',
        'identitystore:DescribeGroup',
        'identitystore:ListGroupMemberships',
        'identitystore:ListGroupMembershipsForMember',
        'identitystore:IsMemberInGroups',
        'organizations:ListAccounts',
      ],
      resources: ['*'], // Identity Center requires wildcard
    });

    messageHandler.function.addToRolePolicy(identityCenterPolicy);
    revocationHandler.function.addToRolePolicy(identityCenterPolicy);

    // Create API Gateway
    const api = new ApiConstruct(this, 'Api', {
      messageHandler: messageHandler.function,
    });

    // Create EventBridge scheduler
    const scheduler = new SchedulerConstruct(this, 'Scheduler', {
      revocationHandler: revocationHandler.function,
      scheduleExpression,
    });

    // Stack outputs
    new CfnOutput(this, 'ApiEndpoint', {
      description: 'Slack webhook URL (configure in Slack app settings)',
      value: `${api.url}slack/events`,
      exportName: 'ApedemakWebhookUrl',
    });

    new CfnOutput(this, 'LeasesTableName', {
      description: 'DynamoDB leases table name',
      value: storage.leasesTable.tableName,
      exportName: 'ApedemakLeasesTable',
    });

    new CfnOutput(this, 'RevocationSchedule', {
      description: 'EventBridge schedule for access revocation',
      value: scheduleExpression,
      exportName: 'ApedemakRevocationSchedule',
    });

    new CfnOutput(this, 'DryRunMode', {
      description: 'Dry-run mode status',
      value: config.dryRunMode ? 'ENABLED (no actual AWS changes)' : 'DISABLED',
    });

    // CDK Nag suppressions for known wildcard resource requirements
    NagSuppressions.addResourceSuppressions(
      [messageHandler.function, revocationHandler.function],
      [
        {
          id: 'AwsSolutions-IAM5',
          reason:
            'Identity Center, Identity Store, and Organizations APIs require wildcard resources. ' +
            'These services do not support resource-level permissions.',
        },
        {
          id: 'AwsSolutions-IAM4',
          reason: 'AWSLambdaBasicExecutionRole is acceptable for CloudWatch Logs access.',
          appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'],
        },
        {
          id: 'AwsSolutions-L1',
          reason: 'Python 3.13 is the latest supported Lambda runtime at time of deployment.',
        },
      ],
      true,
    );

    NagSuppressions.addResourceSuppressions(
      storage.leasesTable,
      [
        {
          id: 'AwsSolutions-DDB3',
          reason: 'PITR not required — leases are short-lived and reconstructable.',
        },
      ],
    );

    NagSuppressions.addResourceSuppressions(
      secrets.accessListSecret,
      [
        {
          id: 'AwsSolutions-SMG4',
          reason: 'Access list secret is managed via CDK config, not a rotatable credential.',
        },
      ],
    );

    NagSuppressions.addResourceSuppressions(
      api.api,
      [
        {
          id: 'AwsSolutions-APIG2',
          reason: 'Request validation is handled in Lambda; Slack sends unstructured payloads.',
        },
        {
          id: 'AwsSolutions-APIG4',
          reason: 'Slack webhooks use signing-secret verification in Lambda, not API GW authorizers.',
        },
        {
          id: 'AwsSolutions-COG4',
          reason: 'Cognito is not applicable — Slack handles its own authentication.',
        },
      ],
      true,
    );
  }
}
