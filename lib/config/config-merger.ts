import { AccessListConfig, MergedAccessConfig } from './config.interface';

/**
 * Merge access list configuration with pseudo-groups for Secrets Manager storage
 * 
 * This produces a single JSON structure that combines the access list and pseudo-groups
 * at the top level for efficient Lambda consumption.
 * 
 * @param accessList - The access list configuration
 * @returns Merged configuration ready for Secrets Manager
 */
export function mergeAccessConfig(accessList: AccessListConfig): MergedAccessConfig {
  return {
    access_list: {
      accounts: accessList.accounts.map(account => ({
        id: account.id,
        name: account.name,
        permission_sets: account.permissionSets.map(ps => ({
          name: ps.name,
          users: ps.users,
          groups: ps.groups,
          approvers: ps.approvers,
        })),
      })),
    },
    pseudo_groups: accessList.pseudoGroups,
  };
}

/**
 * Returns a rate expression based on the shortest duration
 * 
 * @param durations - Array of permission durations in seconds
 * @returns EventBridge schedule expression (e.g., "rate(30 minutes)")
 */
export function calculateScheduleExpression(durations: number[]): string {
  if (!durations || durations.length === 0) {
    throw new Error('Permission durations array cannot be empty');
  }
  
  const minDurationSeconds = Math.min(...durations);
  const minDurationMinutes = Math.floor(minDurationSeconds / 60);
  
  if (minDurationMinutes < 1) {
    throw new Error('Minimum permission duration must be at least 60 seconds');
  }
  
  return `rate(${minDurationMinutes} minutes)`;
}

/**
 * Format permission duration for display in Slack
 * 
 * @param seconds - Duration in seconds
 * @returns Human-readable duration string
 */
export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  
  if (hours > 0 && minutes > 0) {
    return `${hours}h ${minutes}m`;
  } else if (hours > 0) {
    return `${hours} hour${hours !== 1 ? 's' : ''}`;
  } else if (minutes > 0) {
    return `${minutes} minute${minutes !== 1 ? 's' : ''}`;
  } else {
    return `${seconds} seconds`;
  }
}
