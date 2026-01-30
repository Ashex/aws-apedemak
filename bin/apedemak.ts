#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { ApedemakStack } from '../lib/apedemak-stack';
import { defaultConfig, defaultAccessList } from '../lib/config/default.config';

// Validate configuration — reject placeholder values
const placeholderPatterns = [/arn:aws:sso:::instance\/ssinst-placeholder/, /d-placeholder/];
const configValues = [defaultConfig.identityCenterInstanceArn, defaultConfig.identityStoreId];
for (const value of configValues) {
  for (const pattern of placeholderPatterns) {
    if (pattern.test(value)) {
      throw new Error(
        `Configuration contains placeholder value "${value}". ` +
        'Update lib/config/default.config.ts with real values before deploying.',
      );
    }
  }
}

const app = new cdk.App();

// Apply CDK Nag security checks
cdk.Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));

new ApedemakStack(app, 'ApedemakStack', {
  config: defaultConfig,
  accessList: defaultAccessList,
  
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
  
  description: 'Slack-based AWS Identity Center access request management system',
  
  tags: {
    Project: 'Apedemak',
    ManagedBy: 'CDK',
  },
});

app.synth();
