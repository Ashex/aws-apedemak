import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Duration, RemovalPolicy, ILocalBundling, BundlingOptions } from 'aws-cdk-lib';
import * as path from 'path';
import { execSync } from 'child_process';

export interface LambdaFunctionProps {
  readonly functionName: string;
  readonly codePath: string;
  readonly handler?: string;
  readonly memorySize?: number;
  readonly timeout?: Duration;
  readonly environment?: { [key: string]: string };
  readonly logRetention?: logs.RetentionDays;
  readonly provisionedConcurrency?: number;
}


export class LambdaFunction extends Construct {
  public readonly function: lambda.Function;
  public readonly alias?: lambda.Alias;
  public readonly logGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: LambdaFunctionProps) {
    super(scope, id);

    this.logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/aws/lambda/${props.functionName}`,
      retention: props.logRetention || logs.RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // AWS Lambda Powertools Layer (Python, ARM64) resolved via SSM
    const powertoolsLayerArn = ssm.StringParameter.valueForStringParameter(
      this, '/aws/service/powertools/python/arm64/python3.13/latest'
    );
    const powertoolsLayer = lambda.LayerVersion.fromLayerVersionArn(
      this,
      'PowertoolsLayer',
      powertoolsLayerArn
    );

    this.function = new lambda.Function(this, 'Function', {
      functionName: props.functionName,
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: props.handler || 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', props.codePath), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_13.bundlingImage,
          platform: 'linux/arm64',
          local: {
            tryBundle(outputDir: string, _options: BundlingOptions): boolean {
              const inputDir = path.join(__dirname, '..', '..', props.codePath);
              const sharedDir = path.join(__dirname, '..', '..', 'src', 'shared');
              try {
                const reqFile = path.join(inputDir, 'requirements.txt');
                try {
                  execSync(`pip install -r ${reqFile} -t ${outputDir} --quiet`, { stdio: 'pipe' });
                } catch { /* no requirements.txt or pip failed */ }
                execSync(`cp -au ${inputDir}/. ${outputDir}/`);
                execSync(`cp -r ${sharedDir} ${outputDir}/shared`);
                return true;
              } catch {
                return false;
              }
            },
          } as ILocalBundling,
          volumes: [
            {
              hostPath: path.join(__dirname, '..', '..', 'src', 'shared'),
              containerPath: '/shared',
            },
          ],
          command: [
            'bash',
            '-c',
            [
              'if [ -f requirements.txt ]; then pip install -r requirements.txt -t /asset-output; fi',
              'cp -au . /asset-output',
              'cp -r /shared /asset-output/shared',
            ].join(' && '),
          ],
        },
      }),
      memorySize: props.memorySize || 512,
      timeout: props.timeout || Duration.seconds(30),
      environment: {
        ...props.environment,
        POWERTOOLS_SERVICE_NAME: 'apedemak',
        POWERTOOLS_METRICS_NAMESPACE: 'Apedemak',
        POWERTOOLS_LOGGER_LOG_EVENT: 'false',
        POWERTOOLS_TRACE_DISABLED: 'false',
      },
      tracing: lambda.Tracing.ACTIVE,
      logGroup: this.logGroup,
      layers: [powertoolsLayer],
    });

    if (props.provisionedConcurrency && props.provisionedConcurrency > 0) {
      const version = this.function.currentVersion;
      this.alias = new lambda.Alias(this, 'LiveAlias', {
        aliasName: 'live',
        version: version,
        provisionedConcurrentExecutions: props.provisionedConcurrency,
      });
    }
  }
}
