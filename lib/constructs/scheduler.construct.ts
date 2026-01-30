import { Construct } from 'constructs';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as lambda from 'aws-cdk-lib/aws-lambda';

export interface SchedulerConstructProps {
  /** Access revocation Lambda function */
  readonly revocationHandler: lambda.IFunction;
  /** EventBridge schedule expression (e.g., "rate(30 minutes)") */
  readonly scheduleExpression: string;
}

/**
 * EventBridge scheduler construct for periodic access revocation
 */
export class SchedulerConstruct extends Construct {
  /** EventBridge rule */
  public readonly rule: events.Rule;

  constructor(scope: Construct, id: string, props: SchedulerConstructProps) {
    super(scope, id);

    // Create EventBridge rule with dynamic schedule
    this.rule = new events.Rule(this, 'RevocationSchedule', {
      ruleName: 'apedemak-access-revocation',
      description: 'Periodic trigger for Apedemak access lease revocation',
      schedule: events.Schedule.expression(props.scheduleExpression),
      enabled: true,
    });

    // Add Lambda function as target
    this.rule.addTarget(
      new targets.LambdaFunction(props.revocationHandler, {
        retryAttempts: 2,
      })
    );
  }
}
