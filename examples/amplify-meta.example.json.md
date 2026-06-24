# CloudFormation output shape (example)

> This is the shape of an `amplify-meta.json` file (or equivalent CloudFormation output) that the data layer expects to read at startup. The values are placeholders — your actual deployment will have different ARNs and IDs.

---

## What this is for

The data layer uses this file (or the equivalent output from your deployment tool) to learn:

- The Cognito user pool ID
- The Cognito user pool client ID
- The AppSync endpoint URL
- The AppSync API key (if using API key auth)
- The S3 bucket names
- The CloudFront distribution domain
- The IAM role ARNs

If you deploy with AWS Amplify, this file is generated automatically. If you deploy with Terraform, CDK, or another tool, generate an equivalent file.

---

## Example file

```json
{
  "providers": {
    "awscloudformation": {
      "AuthRole": {
        "roleName": "describeat-auth-role",
        "roleArn": "arn:aws:iam::ACCOUNT_ID:role/describeat-auth-role"
      },
      "UnauthRole": {
        "roleName": "describeat-unauth-role",
        "roleArn": "arn:aws:iam::ACCOUNT_ID:role/describeat-unauth-role"
      },
      "AuthRoleName": "describeat-auth-role",
      "UnauthRoleName": "describeat-unauth-role",
      "Region": "us-east-1",
      "ProfileName": "default",
      "StackId": "arn:aws:cloudformation:us-east-1:ACCOUNT_ID:stack/describeat/abc123",
      "AmplifyAppId": "abc123"
    }
  },
  "api": {
    "describeat": {
      "service": "AppSync",
      "output": {
        "GraphQLAPIEndpoint": "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql",
        "GraphQLAPIId": "abc123",
        "GraphQLAPIKey": "da2-XXXXXXXXXXXXXXXXXXXXXXXXXX",
        "AuthenticationType": "AMAZON_COGNITO_USER_POOLS",
        "UserPoolId": "us-east-1_XXXXXXXXX"
      }
    }
  },
  "auth": {
    "describeatuserpool": {
      "service": "Cognito",
      "output": {
        "UserPoolId": "us-east-1_XXXXXXXXX",
        "UserPoolClientId": "xxxxxxxxxxxxxxxxxxxxxxxxxx",
        "UserPoolName": "describeat-app-pool",
        "AppClientSecret": "<REDACTED - use Secrets Manager>",
        "IdentityPoolId": "us-east-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      }
    }
  },
  "storage": {
    "publicBucket": {
      "service": "S3",
      "output": {
        "BucketName": "describeat-public",
        "Region": "us-east-1"
      }
    },
    "privateBucket": {
      "service": "S3",
      "output": {
        "BucketName": "describeat-private",
        "Region": "us-east-1"
      }
    }
  },
  "function": {
    "notificationLambda": {
      "service": "Lambda",
      "output": {
        "Name": "describeat-notification-sender",
        "Arn": "arn:aws:lambda:us-east-1:ACCOUNT_ID:function:describeat-notification-sender",
        "Region": "us-east-1",
        "LambdaExecutionRole": "arn:aws:iam::ACCOUNT_ID:role/describeat-lambda-exec"
      }
    }
  }
}
```

---

## How to use this

### At build time

The PWA reads the relevant fields at build time:

```typescript
// In the PWA's aws-exports.ts
import amplifyMeta from './amplify-meta.json';

export const awsConfig = {
  Auth: {
    userPoolId: amplifyMeta.auth.describeatuserpool.output.UserPoolId,
    userPoolClientId: amplifyMeta.auth.describeatuserpool.output.UserPoolClientId,
    region: amplifyMeta.providers.awscloudformation.Region,
  },
  API: {
    graphqlEndpoint: amplifyMeta.api.describeat.output.GraphQLAPIEndpoint,
    graphqlApiKey: amplifyMeta.api.describeat.output.GraphQLAPIKey,  // if using API key
  },
  Storage: {
    publicBucket: amplifyMeta.storage.publicBucket.output.BucketName,
    publicRegion: amplifyMeta.storage.publicBucket.output.Region,
  },
};
```

### At runtime

The data layer reads this file on startup to configure itself. If you're not using Amplify, you can generate this file from your Terraform/CDK output:

```bash
# Terraform example
terraform output -json > amplify-meta.json
```

```bash
# CDK example
cdk synth --json > amplify-meta.json
```

---

## Security warning

The `GraphQLAPIKey` field is a **secret**. If you're using API key auth (not recommended for production — use Cognito user pool auth), the API key grants full access to your GraphQL API. Anyone with the key can read and write all data.

**Do not commit this file to source control if it contains real values.** Either:
- Use a tool that injects secrets at build time (Amplify's build hooks, Docker secrets, etc.)
- Keep the file out of git (`amplify-meta.local.json` in `.gitignore`)
- Use a different auth mechanism that doesn't require committing secrets (Cognito user pool auth + IAM auth is the recommended approach)

---

## Differences from real Amplify output

The real `amplify-meta.json` has more fields than shown here. The fields shown are the ones that the DescribeAT PWA and data layer actually use. The full file includes:

- `dev` branch information
- `function` definitions with full Lambda config
- `hosting` configuration (S3 + CloudFront)
- `notifications` configuration
- `predictions` configuration (if used)
- `xr` configuration (if used)
- `geo` configuration (if used)

These are not relevant to DescribeAT and can be omitted.
