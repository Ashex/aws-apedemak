import { Construct } from 'constructs';
import * as cdk from 'aws-cdk-lib';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { MergedAccessConfig } from '../config/config.interface';

export interface SecretsConstructProps {
  /** Merged access configuration to store */
  readonly accessConfig: MergedAccessConfig;
}

export class SecretsConstruct extends Construct {
  public readonly slackSecret: secretsmanager.ISecret;
  public readonly accessListSecret: secretsmanager.Secret;

  constructor(scope: Construct, id: string, props: SecretsConstructProps) {
    super(scope, id);

    // Reference existing Slack credentials secret
    // This must be created manually before deployment with:
    // aws secretsmanager create-secret --name apedemak/slack-credentials \
    //   --secret-string '{"bot_token":"xoxb-...","signing_secret":"..."}'
    this.slackSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'SlackCredentials',
      'apedemak/slack-credentials'
    );


    this.accessListSecret = new secretsmanager.Secret(this, 'AccessListSecret', {
      secretName: 'apedemak/access-list',
      description: 'access list configuration for Apedemak',
      secretObjectValue: {
        access_list: cdk.SecretValue.unsafePlainText(
          JSON.stringify(props.accessConfig.access_list)
        ),
        pseudo_groups: cdk.SecretValue.unsafePlainText(
          JSON.stringify(props.accessConfig.pseudo_groups)
        ),
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
  }
}
