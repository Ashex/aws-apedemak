import { ApedemakConfig, AccessListConfig } from './config.interface';

/**
 * Default Apedemak configuration
 * 
 * Customize these values for your environment
 */
export const defaultConfig: ApedemakConfig = {
  // Permission duration options (in hh:mm format)
  // [30 min, 1 hour, 4 hours, 8 hours]
  permissionDurations: ['00:30', '01:00', '04:00', '08:00'],
  
  // Slack channel ID for access requests (get from Slack channel details)
  slackChannel: 'C0123456789',
  
  // Logging level
  logLevel: 'INFO',
  
  // Dry-run mode: set to true for testing without actual AWS changes
  dryRunMode: false,
  
  // Request expires after 1 hour if not approved
  requestExpirationSeconds: 3600,
  
  // Send reminders every 15 minutes
  reminderIntervalSeconds: 900,
  
  // Reminder backoff multiplier (1.5 = 15min, 22.5min, 33.75min...)
  reminderBackoff: 1.5,
  
  // Identity Center instance ARN (update with your instance)
  identityCenterInstanceArn: 'arn:aws:sso:::instance/ssoins-1234567890abcdef',
  
  // Identity store ID (update with your store)
  identityStoreId: 'd-1234567890',
};

/**
 * Example access list configuration
 * 
 * Define which users/groups can access which accounts and permission sets
 */
export const defaultAccessList: AccessListConfig = {
  accounts: [
    {
      id: '123456789012',
      name: 'Production',
      permissionSets: [
        {
          name: 'ReadOnlyAccess',
          users: ['user@example.com'],
          groups: ['developers'],
          approvers: ['lead@example.com', 'manager@example.com'],
        },
        {
          name: 'DeveloperAccess',
          users: [],
          groups: ['senior-developers'],
          approvers: ['lead@example.com'],
        },
        {
          name: 'AdministratorAccess',
          users: [],
          groups: ['pseudo:principal-engineers'], // This is a pseudo-group defined below
          approvers: [], // Empty = self-approval
        },
      ],
    },
    {
      id: '210987654321',
      name: 'Staging',
      permissionSets: [
        {
          name: 'DeveloperAccess',
          users: [],
          groups: ['developers', 'qa-team'],
          approvers: [], // Self-approval for staging
        },
        {
          name: 'AdministratorAccess',
          users: [],
          groups: ['platform-team'],
          approvers: [],
        },
      ],
    },
    {
      id: '111122223333',
      name: 'Development',
      permissionSets: [
        {
          name: 'DeveloperAccess',
          users: [],
          groups: ['developers'],
          approvers: [], // Self-approval for dev environment
        },
      ],
    },
  ],
  
  // Pseudo-groups: custom groups not in Identity Center
  // Useful for cross-cutting access patterns (e.g., principal engineers, on-call)
  // Must be prefixed with 'pseudo:' to avoid group collisions
  pseudoGroups: {
    'pseudo:principal-engineers': [
      'pe1@example.com',
      'pe2@example.com',
      'pe3@example.com',
    ],
    'pseudo:on-call-team': [
      'oncall1@example.com',
      'oncall2@example.com',
    ],
  },
};
