import { Construct } from 'constructs';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Duration, RemovalPolicy } from 'aws-cdk-lib';

export interface ApiConstructProps {

  readonly messageHandler: lambda.IFunction;
}

/**
 * API Gateway construct for webhook endpoints
 */
export class ApiConstruct extends Construct {
  /** REST API Gateway */
  public readonly api: apigateway.RestApi;
  
  /** API endpoint URL */
  public readonly url: string;

  constructor(scope: Construct, id: string, props: ApiConstructProps) {
    super(scope, id);

    const accessLogGroup = new logs.LogGroup(this, 'AccessLogs', {
      logGroupName: '/aws/apigateway/apedemak-api',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // Create REST API Gateway
    this.api = new apigateway.RestApi(this, 'Api', {
      restApiName: 'apedemak-api',
      description: 'Messaging platform webhook endpoint for Apedemak access requests',
      deployOptions: {
        stageName: 'prod',
        tracingEnabled: true,
        throttlingRateLimit: 100,
        throttlingBurstLimit: 200,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: false,
        accessLogDestination: new apigateway.LogGroupLogDestination(accessLogGroup),
        accessLogFormat: apigateway.AccessLogFormat.jsonWithStandardFields(),
      },
      // Disable default CORS (messaging platforms don't need it)
      defaultCorsPreflightOptions: undefined,
    });

    // Create /slack resource (maintaining backward compatibility with Slack setup)
    const slackResource = this.api.root.addResource('slack');
    
    // Create /slack/events endpoint for all messaging platform interactions
    const eventsResource = slackResource.addResource('events');
    
    // POST /slack/events - handles all messaging platform webhooks
    eventsResource.addMethod(
      'POST',
      new apigateway.LambdaIntegration(props.messageHandler, {
        timeout: Duration.seconds(29), // API Gateway max timeout
        proxy: true,
      }),
      {
        requestValidatorOptions: {
          validateRequestBody: false,
          validateRequestParameters: false,
        },
      }
    );

    this.url = this.api.url;
  }
}
