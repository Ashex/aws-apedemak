import { Construct } from 'constructs';
import * as logs from 'aws-cdk-lib/aws-logs';
import { RemovalPolicy } from 'aws-cdk-lib';

/**
 * Monitoring construct for audit logging
 */
export class AuditingConstruct extends Construct {
  /** Audit log group for Message handler */
  public readonly messageAuditLogGroup: logs.LogGroup;
  
  /** Audit log group for access revocation */
  public readonly revocationAuditLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    // Create dedicated audit log groups with extended retention
    this.messageAuditLogGroup = new logs.LogGroup(this, 'MessageAuditLogs', {
      logGroupName: '/aws/access/apedemak-message-handler-audit',
      retention: logs.RetentionDays.SIX_MONTHS, // Extended retention for audit
      removalPolicy: RemovalPolicy.RETAIN, // Retain logs even if stack is deleted
    });

    this.revocationAuditLogGroup = new logs.LogGroup(this, 'RevocationAuditLogs', {
      logGroupName: '/aws/access/apedemak-access-revocation-audit',
      retention: logs.RetentionDays.SIX_MONTHS,
      removalPolicy: RemovalPolicy.RETAIN,
    });
  }
}
