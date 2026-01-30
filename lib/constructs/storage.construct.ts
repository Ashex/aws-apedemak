import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { RemovalPolicy } from 'aws-cdk-lib';

/**
 * Storage construct for DynamoDB tables
 */
export class StorageConstruct extends Construct {
  /** DynamoDB table for access leases */
  public readonly leasesTable: dynamodb.Table;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    // Create leases table with GSIs for efficient querying
    this.leasesTable = new dynamodb.Table(this, 'LeasesTable', {
      tableName: 'apedemak-leases',
      partitionKey: {
        name: 'lease_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: RemovalPolicy.DESTROY,
      timeToLiveAttribute: 'ttl',
    });

    // GSI for querying expired leases
    // Query pattern: status = 'ACTIVE' AND expires_at < now
    this.leasesTable.addGlobalSecondaryIndex({
      indexName: 'ExpirationIndex',
      partitionKey: {
        name: 'status',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'expires_at',
        type: dynamodb.AttributeType.NUMBER,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for querying user's lease history
    // Query pattern: user_email = 'user@example.com' ORDER BY created_at DESC
    this.leasesTable.addGlobalSecondaryIndex({
      indexName: 'UserIndex',
      partitionKey: {
        name: 'user_email',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'created_at',
        type: dynamodb.AttributeType.NUMBER,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });
  }
}
