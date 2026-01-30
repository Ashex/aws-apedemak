/**
 * Permission set configuration for an account
 */
export interface PermissionSetConfig {
  /** Permission set name (must exist in Identity Center) */
  readonly name: string;
  /** User emails with direct access */
  readonly users: string[];
  /** Identity Center group names */
  readonly groups: string[];
  /** Approver emails (empty array for self-approval) */
  readonly approvers: string[];
}

/**
 * AWS account configuration
 */
export interface AccountConfig {
  /** AWS account ID */
  readonly id: string;
  /** Human-readable account name */
  readonly name: string;
  /** Available permission sets for this account */
  readonly permissionSets: PermissionSetConfig[];
}

/**
 * Access list configuration mapping accounts to permission sets and users
 */
export interface AccessListConfig {
  /** List of AWS accounts with their permission configurations */
  readonly accounts: AccountConfig[];
  /** Pseudo-groups: custom groups not in Identity Center */
  readonly pseudoGroups: { [groupName: string]: string[] };
}

/**
 * Main Apedemak configuration
 */
export interface ApedemakConfig {
  /** Available permission duration options in hh:mm format (e.g., ['01:00', '04:00'] for 1hr, 4hr) */
  readonly permissionDurations: string[];
  /** Slack channel ID for access requests */
  readonly slackChannel: string;
  /** Log level for Lambda functions */
  readonly logLevel: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
  /** Enable dry-run mode (no actual AWS changes) */
  readonly dryRunMode: boolean;
  /** Request expiration time in seconds */
  readonly requestExpirationSeconds: number;
  /** Reminder interval in seconds */
  readonly reminderIntervalSeconds: number;
  /** Reminder backoff multiplier */
  readonly reminderBackoff: number;
  /** AWS Identity Center instance ARN */
  readonly identityCenterInstanceArn: string;
  /** Identity store ID for user lookups */
  readonly identityStoreId: string;
}

/**
 * Merged configuration stored in Secrets Manager
 */
export interface MergedAccessConfig {
  /** Access list with accounts and permission sets */
  readonly access_list: {
    readonly accounts: Array<{
      readonly id: string;
      readonly name: string;
      readonly permission_sets: Array<{
        readonly name: string;
        readonly users: string[];
        readonly groups: string[];
        readonly approvers: string[];
      }>;
    }>;
  };
  /** Pseudo-groups at top level */
  readonly pseudo_groups: { [groupName: string]: string[] };
}

/**
 * Slack credentials stored in Secrets Manager
 */
export interface SlackCredentials {
  readonly bot_token: string;
  readonly signing_secret: string;
}
