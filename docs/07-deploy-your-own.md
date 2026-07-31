# 07 — Deploy Your Own

> Step-by-step: bring up your own DescribeAT backend.

---

## Before you start

This guide assumes:

- You have a cloud account (AWS recommended, but the architecture works on any cloud)
- You're comfortable with the basics of deploying serverless/containerised services
- You have a domain name you control
- You have chosen your fingerprinting engine (see [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md))

**Total time:** 2-4 days for a basic deployment, 1-2 weeks for a production-ready one.

**Total cost:** ~$50-150/month for a small deployment. See [`08-cost-estimates.md`](08-cost-estimates.md).

---

## The 8-step deployment

### Step 1: Domain and DNS

You need a domain for the listeners to access the PWA. You also need subdomains for the various services.

**Subdomains you'll need:**

| Subdomain | Purpose | Points to |
|-----------|---------|-----------|
| `app.{your-domain}` | The PWA itself | CDN |
| `api.{your-domain}` | The data layer (GraphQL) | CDN → data layer origin |
| `t2s.{your-domain}` | The fingerprinting engine | CDN → matcher origin |
| `media.{your-domain}` | AD track audio, posters | CDN → public bucket |
| `auth.{your-domain}` | OAuth hosted UI | Auth provider |
| `admin.{your-domain}` | The admin portal | CDN |

**DNS configuration:** Add the subdomains as CNAMEs to the CDN, or as A records to the CDN's anycast IPs.

**TLS certificates:** Most CDNs (CloudFront, Cloudflare) issue free TLS certificates. For custom origins, use ACM or Let's Encrypt.

---

### Step 2: Auth provider

Set up the two pools as described in [`02-auth.md`](02-auth.md).

**For AWS Cognito:**

```bash
# Create the app pool
aws cognito-idp create-user-pool \
  --pool-name "describeat-app-pool" \
  --auto-verified-attributes email \
  --username-attributes email

# Create the admin pool (with domain allowlist)
aws cognito-idp create-user-pool \
  --pool-name "describeat-admin-pool" \
  --auto-verified-attributes email \
  --username-attributes email \
  --lambda-config "PreSignUp=arn:aws:lambda:REGION:ACCOUNT:function:domain-allowlist"

# Create an OAuth client for the app pool
aws cognito-idp create-user-pool-client \
  --user-pool-id "APP_POOL_ID" \
  --client-name "describeat-app-web" \
  --generate-secret \
  --allowed-o-auth-flows "code" \
  --allowed-o-auth-scopes "openid email profile" \
  --callback-urls "https://app.{your-domain}/auth/callback"

# Create an OAuth client for the admin pool
aws cognito-idp create-user-pool-client \
  --user-pool-id "ADMIN_POOL_ID" \
  --client-name "describeat-admin-web" \
  --generate-secret \
  --allowed-o-auth-flows "code" \
  --allowed-o-auth-scopes "openid email profile" \
  --callback-urls "https://admin.{your-domain}/auth/callback"
```

The `domain-allowlist` Lambda:

```javascript
exports.handler = async (event) => {
  const email = event.request.userAttributes.email;
  const allowedDomains = ['your-org.com', 'partners.org'];  // ← YOUR DOMAINS
  const domain = email.split('@')[1];
  if (!allowedDomains.includes(domain)) {
    throw new Error('Sign-up is not allowed for this email domain.');
  }
  return event;
};
```

**For non-AWS providers (Auth0, Keycloak, Clerk):** Follow their respective documentation for the equivalent setup. The two-pool model is the same regardless of provider.

---

### Step 3: Storage

Create the two buckets.

```bash
# Public bucket
aws s3api create-bucket \
  --bucket "{your-name}-describeat-public" \
  --region "us-east-1"  # or your preferred region

# Block all public access; the CDN will use OAC (Origin Access Control)
aws s3api put-public-access-block \
  --bucket "{your-name}-describeat-public" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Private bucket
aws s3api create-bucket \
  --bucket "{your-name}-describeat-private" \
  --region "us-east-1"

# Private bucket: no public access, signed URLs only
aws s3api put-public-access-block \
  --bucket "{your-name}-describeat-private" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

Set up lifecycle policies to delete the admin upload staging after 24 hours.

---

### Step 4: Data layer

You have three main options:

#### Option A: AWS AppSync + DynamoDB (managed, AWS-only)

Pros: Easiest on AWS. Cons: Vendor lock-in.

```bash
# Define the GraphQL schema (use the schema from this repo's docs/03-data-model.md)
# Use AWS AppSync to deploy the API
# Use DynamoDB tables for each entity
# Use IAM auth or Cognito user pool auth
```

#### Option B: Hasura + Postgres (open-source, portable)

Pros: Open-source, portable to any cloud. Cons: More setup.

```bash
# Deploy Hasura (Docker container or Hasura Cloud)
# Create Postgres database
# Connect Hasura to Postgres
# Define tables matching the schema in this repo
# Set up permissions (per-user vs admin)
# Expose GraphQL endpoint
```

#### Option C: Custom GraphQL server (most flexible)

Pros: Total control. Cons: Most work.

Use Apollo Server, GraphQL Yoga, or similar. Implement the resolvers, auth, and authorization yourself.

**For most self-hosters:** **Option B (Hasura + Postgres)** is the best balance. You get a real GraphQL API without vendor lock-in, and the migration path to a custom solution is straightforward.

---

### Step 5: Fingerprinting engine

#### Matcher (always-on)

**For Dejavu-based:**

```dockerfile
FROM python:3.11-slim

RUN pip install dejavu-python flask gunicorn

COPY matcher.py /app/matcher.py
COPY fingerprints/ /app/fingerprints/

WORKDIR /app

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "matcher:app"]
```

The matcher loads the fingerprint database at startup. Memory usage depends on the size of your catalogue (~1 GB per 1000 AD tracks).

**For commercial library:** Follow the vendor's deployment guide. The pattern is the same — a stateless HTTP service that takes audio in, returns a match out.

**Deployment:** Run 2-4 instances behind a load balancer. Each instance holds the same fingerprint database in memory. The load balancer distributes requests across instances.

#### Fingerprinter (on-demand)

Same image as the matcher, but with a different entry point. The fingerprinter is triggered by an event (S3 upload, scheduled task, etc.).

**For AWS Fargate:** Set desired count to 0. Use a Lambda to start a new task when needed; the task scales back to 0 after processing.

**For Kubernetes:** Use a Job or Deployment with HPA. Set min replicas to 0.

**For a simple server:** Run on a small instance. Trigger via cron or webhook. Scale manually if needed.

---

### Step 6: CDN

Set up the CDN with the routing rules from [`05-storage-cdn.md`](05-storage-cdn.md).

**For AWS CloudFront:**

```yaml
# cloudfront-config.yaml
DistributionConfig:
  Origins:
    - Id: public-bucket
      DomainName: "{your-name}-describeat-public.s3.amazonaws.com"
      S3OriginConfig:
        OriginAccessIdentity: "origin-access-identity/cloudfront/OAI_ID"
    - Id: data-layer
      DomainName: "api.{your-domain}"
      CustomOriginConfig:
        HTTPPort: 443
        OriginProtocolPolicy: https-only
    - Id: matcher
      DomainName: "t2s.{your-domain}"
      CustomOriginConfig:
        HTTPPort: 443
        OriginProtocolPolicy: https-only

  DefaultCacheBehavior:
    TargetOriginId: public-bucket
    ViewerProtocolPolicy: redirect-to-https
    AllowedMethods: [GET, HEAD, OPTIONS]
    CachedMethods: [GET, HEAD]
    TTL: 300

  CacheBehaviors:
    - PathPattern: "/t2s/*"
      TargetOriginId: matcher
      ViewerProtocolPolicy: redirect-to-https
      AllowedMethods: [GET, HEAD, OPTIONS, POST]
      CachedMethods: []
      TTL: 0
      Forward: "QueryString"
    - PathPattern: "/api/*"
      TargetOriginId: data-layer
      ViewerProtocolPolicy: redirect-to-https
      AllowedMethods: [GET, HEAD, OPTIONS, POST]
      CachedMethods: []
      TTL: 0
    - PathPattern: "/media/*"
      TargetOriginId: public-bucket
      ViewerProtocolPolicy: redirect-to-https
      AllowedMethods: [GET, HEAD]
      CachedMethods: [GET, HEAD]
      TTL: 2592000  # 30 days

  Aliases:
    - "app.{your-domain}"
    - "api.{your-domain}"
    - "t2s.{your-domain}"
    - "media.{your-domain}"

  ViewerCertificate:
    AcmCertificateArn: "arn:aws:acm:..."
    SslSupportMethod: sni-only
```

---

### Step 7: Point the PWA at your backend

The DescribeAT PWA (in the [`describeat-app`](https://github.com/ShazaCin/describeat-app-public) repository) needs to know your backend endpoints. These are environment variables in the PWA's build:

```bash
# .env.production
VITE_API_ENDPOINT=https://api.{your-domain}/graphql
VITE_T2S_ENDPOINT=https://t2s.{your-domain}/t2s/sync
VITE_MEDIA_CDN_BASE=https://media.{your-domain}
VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXX
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxx
VITE_COGNITO_DOMAIN=auth.{your-domain}
```

Build the PWA and deploy the static assets to your public bucket.

---

### Step 8: Test, test, test

Before going live:

- [ ] **End-to-end sync test:** Record 5 different shows with known titleIds, verify all 5 return matches with confidence > 0.85
- [ ] **iOS push test:** Install the PWA on an iOS device, add to home screen, grant notification permission, send a test notification, verify it arrives
- [ ] **Android push test:** Same on Android
- [ ] **Web push test:** Same on Chrome, Firefox, Edge
- [ ] **Admin flow test:** Sign in as admin, upload a new title, verify the title appears in the app
- [ ] **Fingerprinting pipeline test:** Upload a new AD track, verify it gets fingerprinted and matchable within 5 minutes
- [ ] **Auth boundary test:** Verify a listener cannot read another listener's feedback
- [ ] **Domain allowlist test:** Verify a non-allowlisted email cannot sign up as admin
- [ ] **Load test:** Send 100 concurrent sync requests, verify the matcher returns within 3 seconds for all of them
- [ ] **Failover test:** Take down the matcher, verify the system returns 503 (not 500 or hangs)
- [ ] **Backup test:** Restore a backup to a test environment, verify it works

---

## Going live

When all tests pass:

1. Set the DNS to point to the production CDN
2. Enable monitoring and alerting
3. Document the on-call rotation
4. Publish a status page
5. Announce to your users

---

## After going live

The first week is the hardest. Plan to be available for questions and bug fixes.

- **Day 1-3:** Watch the metrics. Fix any issues that show up in the first 100 users.
- **Day 4-7:** Tune the fingerprinting parameters based on real-world match rates.
- **Week 2+:** Settle into steady-state operations.

---

## What to do if something goes wrong

See [`workflows/incident-response.md`](../workflows/incident-response.md) for the runbook.

---

## Contributing improvements back

If you deploy DescribeAT and find something the docs got wrong, or you build a tool that other deployers would benefit from, please contribute it back. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

The strength of an open-source project is the cumulative improvements from the community. Don't keep your improvements to yourself.

---

## Next

- [`08-cost-estimates.md`](08-cost-estimates.md) — what to budget
- [`09-orphaned-resources.md`](09-orphaned-resources.md) — keeping your account tidy
- [`10-adrs.md`](10-adrs.md) — why we made the choices we did
