# 11 — Troubleshooting & FAQ

> Common issues, known gotchas, and answers to the questions every new DescribeAT contributor eventually asks.

This document complements the deployment guide ([`07-deploy-your-own.md`](07-deploy-your-own.md)) and the per-subsystem docs. Where a problem has a real-world root cause we've already hit in the reference deployment, we cite it directly so you can recognise the symptom faster.

---

## How to use this doc

- **Got a symptom?** Jump to the relevant section by name (Setup, Deployment, T2S, Firebase, Admin, Data Model, Cost).
- **Each issue is written as:** Symptom → Likely cause → Diagnostic command → Fix.
- **The "Why this happens" line** explains the underlying mechanism so you can generalise the fix.
- **FAQ items** are at the bottom, grouped by topic. Skim them before opening an issue — your question is probably already answered.

> **A note on terminology:** DescribeAT was originally developed under the codename "Shazacin" (a portmanteau of *shazam* + *cinema*). Some AWS resource names, environment variables, and IAM role names in the reference deployment still carry this legacy (e.g. `shazacin-t2s`, `DOMAINWHITELIST`). When you see "shazacin" in a config, read it as "describeat". The open-source release keeps the original names where they're load-bearing — renaming mid-release would break existing deployments.

---

## Common Setup Issues

### S1. Cognito user pool creation fails with "Cannot find a user pool with the name..."

**Symptom:** `amplify push` or `aws cognito-idp create-user-pool` fails with `ResourceNotFoundException` despite the pool existing in the console.

**Cause:** The pool was created in a different region than your CLI is pointing at. The reference deployment's app pool (`eu-west-1_gdo3NUHbn`) lives in `eu-west-1`; if you copied `aws-exports.ts` verbatim and your CLI default is `us-east-1`, you'll get this error.

**Diagnostic:**
```bash
aws cognito-idp describe-user-pool --user-pool-id eu-west-1_gdo3NUHbn --region eu-west-1
aws configure get region  # what your CLI defaults to
```

**Fix:** Set `AWS_DEFAULT_REGION=eu-west-1` (or your target region) on every AWS CLI command, or run `aws configure set region eu-west-1`.

**Why this happens:** Cognito pool IDs are region-scoped. A pool ID is meaningless without its region prefix — but Amplify-generated code (`aws-exports.ts`) omits the region and expects the SDK to infer it from `aws_appsync_region` / `aws_cognito_region`. If those env vars aren't set, the SDK falls back to the SDK default, which may differ from where the pool lives.

---

### S2. AppSync returns "Unauthorized" on the first request from a fresh frontend

**Symptom:** You clone the frontend, run `npm install && npm run dev`, point it at your AppSync endpoint, and the first GraphQL query returns `UnauthorizedException`.

**Cause:** The reference deployment uses **API key auth as the default mode** on the SAM App AppSync API (`75tdkx...`). The API key is committed to `aws-exports.ts:18`. When you deploy your own AppSync, a new API key is generated — but the committed `aws-exports.ts` still carries the old (now-invalid) key.

**Diagnostic:**
```bash
# List API keys for your AppSync API
aws appsync list-api-keys --api-id YOUR_API_ID --region eu-west-1
# Compare against what's in your aws-exports.ts
grep -n "aws_appsync_apiKey" describeat-app-frontend-26/aws-exports.ts
```

**Fix:** Regenerate `aws-exports.ts` from your own Amplify project (`amplify pull`), or manually replace the `aws_appsync_apiKey` value with your new API key.

**Why this happens:** The original team committed `aws-exports.ts` to the repo (a separate security issue — see FAQ Q3). AppSync API keys are not secrets in the OAuth sense, but they're per-API-instance — copying them across deployments does not work.

> **Security note:** AppSync API keys are **not** bearer tokens for user data. They authorise the *API*, not the *user*. User-scoped authorisation (whose feedback can this user read?) is enforced by Cognito user pool JWT auth layered on top. Don't rely on API key auth for anything user-sensitive.

---

### S3. S3 uploads from the PWA fail with CORS errors

**Symptom:** Browser console shows `Access to fetch at 'https://shazacin-static-content.s3... blocked by CORS policy` when the PWA tries to upload feedback attachments.

**Cause:** The reference bucket's CORS config only allows specific origins: `app.shazacin.com`, `cxrt3b.shazacin.com`, `admin.shazacin.com`, `describeat.web.app`, `describeat.firebaseapp.com`, `localhost`, `localhost:8080`, `localhost:5173`, `shazacin.com`. If your dev server runs on port 5174 (Vite's fallback when 5173 is taken), it's blocked.

**Diagnostic:**
```bash
aws s3api get-bucket-cors --bucket shazacin-static-content --region eu-west-1
# Check whether your dev origin appears in AllowedOrigins
```

**Fix:** Add your origin to the bucket's CORS configuration:
```bash
cat > /tmp/cors.json <<'EOF'
{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["HEAD", "GET", "PUT", "POST", "DELETE"],
      "AllowedOrigins": [
        "http://localhost:5173",
        "http://localhost:5174",
        "https://app.your-domain"
      ],
      "ExposeHeaders": [
        "Accept-Ranges", "Content-Range", "Content-Encoding",
        "Content-Length", "ETag", "x-amz-request-id", "x-amz-id-2"
      ],
      "MaxAgeSeconds": 3000
    }
  ]
}
EOF
aws s3api put-bucket-cors --bucket shazacin-static-content --cors-configuration file:///tmp/cors.json --region eu-west-1
```

**Why this happens:** S3 CORS is enforced at the browser, not the SDK. The AWS SDK reads the bucket's CORS config and aborts the request if the origin isn't listed. The error message points at the SDK call, not at S3 — which is misleading.

---

### S4. IAM permission denied when Lambda tries to write to DynamoDB

**Symptom:** CloudWatch logs for `combined_lambda` or `audio-transcoder` show `AccessDeniedException: User: arn:aws:sts::...:assumed-role/... is not authorized to perform: dynamodb:PutItem`.

**Cause:** The Lambda's execution role doesn't have `dynamodb:PutItem` / `UpdateItem` on the target table ARN. The reference deployment's IAM roles are scoped to specific table ARNs — if you recreated the tables with new names, the policies still point at the old ARNs.

**Diagnostic:**
```bash
# Get the Lambda's role and its policies
aws lambda get-function-configuration --function-name combined_lambda --region eu-west-1 --query 'Role' --output text
# Then describe the role's inline + attached policies
ROLE_NAME=$(aws lambda get-function-configuration --function-name combined_lambda --query 'Role' --output text --region eu-west-1 | sed 's|.*/||')
aws iam list-role-policies --role-name "$ROLE_NAME"
aws iam list-attached-role-policies --role-name "$ROLE_NAME"
```

**Fix:** Update the role's inline policy to grant access to the new table ARNs. Or — if you're rebuilding from scratch — define your table names in a config map (`config/tables.json`) and parameterise your IAM policies from that map.

**Why this happens:** The Amplify CLI generates per-table IAM scopes at `amplify push` time. If you rename a table after the fact, the old policy becomes stale. This is the single most common IAM bug in Amplify-managed stacks.

---

## Deployment Issues

### D1. CloudFront distribution stuck in "InProgress" for over an hour

**Symptom:** You create a new CloudFront distribution and `aws cloudfront get-distribution` shows `Status=InProgress` for 60+ minutes.

**Cause:** CloudFront deployments normally take 5–15 minutes. If it's stuck past 30 minutes, the most common cause is an **ACM certificate in the wrong region**. CloudFront requires certificates to be in `us-east-1` — no other region works, even if your distribution's origins are in `eu-west-1`.

**Diagnostic:**
```bash
# The reference deployment keeps all ACM certs in us-east-1 — confirm yours is too
aws acm list-certificates --region us-east-1 --output table
aws acm list-certificates --region eu-west-1 --output table  # should NOT include your CloudFront cert
```

**Fix:** Re-issue the certificate in `us-east-1`, re-point your distribution's `AcmCertificateArn` to the new ARN, and redeploy.

**Why this happens:** This is a hard CloudFront constraint — not a bug. ACM is a regional service; CloudFront is global. The only region CloudFront trusts for ACM is `us-east-1`. The reference deployment's certs (`app.shazacin.com`, `admin.shazacin.com`, `auth.shazacin.com`, etc.) are all in `us-east-1` — see [`00-inventory.md §12`](https://example.com/inventory) for the list.

---

### D2. "Amplify vs CDK" — which one should I use?

**Symptom:** You're starting from the open-source repo, and the docs reference both `amplify/backend/amplify-meta.json` and `cdk-notifications-api/lib/NotificationsApiStack.ts`. You don't know which tool to use to deploy.

**Cause:** The reference deployment was created almost entirely via `amplify push` (the Amplify CLI). The only piece of CDK in the entire backend is `NotificationsApiStack.ts` — a 56-line stack that provisions the API Gateway + fcmTokensAPI Lambda for push token registration.

**Diagnostic:** Search the repo:
```bash
find . -name "amplify-meta.json" -o -name "*.stack.ts" -o -name "cdk.json"
```

**Recommendation:**

| What you're deploying | Use | Why |
|---|---|---|
| Cognito user pools + clients | Amplify CLI | Amplify generates the Cognito CFN + IAM roles + Hosted UI custom resources. Replicating this by hand in CDK takes 200+ lines per pool. |
| AppSync APIs + resolvers | Amplify CLI (or AWS Console) | Amplify's GraphQL transform handles resolver generation. CDK has no equivalent — you'd write Velocity templates by hand. |
| DynamoDB tables (auto-provisioned by Amplify) | Amplify CLI | Amplify generates the tables as part of the GraphQL transform. |
| **Push token registration endpoint** (`/register` POST → Lambda) | **CDK** | The only piece that was originally written in CDK. Portable, idempotent, no Amplify state to manage. |
| T2S sync engine (EC2 + ECS + ALB) | CDK or CloudFormation | Not Amplify-managed. The reference deployment was created via Console clicks; reconstruct in CDK or Terraform. |
| CloudFront distributions | CDK or raw CloudFront config | Amplify Hosting creates its own CloudFront for hosting — for custom distributions, use CDK. |

**The pragmatic answer:** Use Amplify CLI for auth + AppSync + DynamoDB (it's the path of least resistance). Use CDK for everything else (T2S, custom CloudFront, custom Lambda triggers). Don't try to migrate Amplify-managed resources to CDK mid-flight — you'll end up with split-brain state.

---

### D3. Custom domain not serving — "Certificate is not yet validated"

**Symptom:** You attach a custom domain (`app.your-domain`) to CloudFront, and the distribution's `ViewerCertificate` shows `Certificate is not yet validated`.

**Cause:** The ACM certificate for your custom domain is in `Pending validation` status — you haven't completed DNS validation.

**Diagnostic:**
```bash
aws acm describe-certificate --certificate-arn arn:aws:acm:us-east-1:ACCOUNT:certificate/CERT_ID --region us-east-1 --query 'Certificate.DomainValidationOptions[].{Domain:DomainName,ValidationDomain:ValidationDomain,Status:ValidationStatus,CNAME:ResourceRecord.Name,Value:ResourceRecord.Value}' --output table
```

**Fix:** Add the CNAME record from the output to your DNS provider (Route53, Cloudflare, etc.). Validation typically completes within 5–10 minutes once DNS propagates.

**Why this happens:** ACM supports both email validation and DNS validation. The reference deployment uses DNS validation (faster, no email round-trip). Forgetting to add the validation CNAME is the single most common cause of stuck distributions.

---

### D4. Cognito Hosted UI custom domain fails with "Domain already exists"

**Symptom:** `aws cognito-idp create-user-pool-domain --domain auth.your-domain --user-pool-id POOL_ID` returns `Domain already exists`.

**Cause:** Cognito custom domains are globally unique. The previous deploy (or another account) already registered the same domain prefix. The reference deployment's `auth.shazacin.com` is one such prefix — you can't reuse it.

**Fix:** Use a different domain prefix that's globally unique. If you need to reclaim a prefix from a stale pool, you must first delete the old user pool (which requires deleting its domain first).

```bash
# Find the pool that owns the prefix
aws cognito-idp describe-user-pool-domain --domain auth.your-domain-prefix --region eu-west-1
# If it's a stale pool you own, delete its domain first:
aws cognito-idp delete-user-pool-domain --domain auth.your-domain-prefix --user-pool-id OLD_POOL_ID --region eu-west-1
# Now you can re-create on your pool
aws cognito-idp create-user-pool-domain --domain auth.your-domain-prefix --user-pool-id POOL_ID --region eu-west-1
```

---

## T2S Engine Issues

### T1. The fingerprinter EC2 instance won't start

**Symptom:** `aws ec2 start-instances --instance-ids i-04821c5781bfa4471` returns success, but the instance state cycles through `pending` → `stopped` and never reaches `running`.

**Cause:** The reference deployment's fingerprinter is a **plain EC2 r5.4xlarge** (16 vCPU / 128 GB RAM), not an ECS Fargate cluster as some early docs implied. If it won't start, the most common reasons are:

1. The instance has no IAM instance profile attached (true in the reference deployment — the instance runs as root with full EC2 metadata access, but no IAM role).
2. The AMI (`ami-08a2aed6e0a6f9c7d`, a custom `ShazaCinT2S-backup` AMI) was deleted or moved to a different account.
3. The EBS volume (`/dev/xvda`, 8GB gp2, **not encrypted**) was detached or deleted.
4. You're in a different region than the instance was created in (eu-west-1 in the reference deployment).

**Diagnostic:**
```bash
aws ec2 describe-instances --instance-ids i-04821c5781bfa4471 --region eu-west-1 \
  --query 'Reservations[0].Instances[0].{State:State.Name,AMI:ImageId,IamProfile:IamInstanceProfile,RootDevice:RootDeviceName,Volumes:BlockDeviceMappings}' \
  --output table

# Check the AMI still exists
aws ec2 describe-images --image-ids ami-08a2aed6e0a6f9c7d --region eu-west-1
```

**Fix:**
- If the AMI is missing: rebuild from the source repo or a backup AMI.
- If the volume is detached: `aws ec2 attach-volume --instance-id i-04821c5781bfa4471 --volume-id vol-xxx --device /dev/xvda`.
- If there's no IAM profile: the reference deployment deliberately omits one. This is a known limitation — without an instance profile, the EC2 can't invoke Lambda, can't access S3 via IAM (it has to use hardcoded credentials instead), and can't use SSM. See FAQ Q12 for the full implications.

**Why this happens:** The original team's cost-saving strategy was to stop the r5.4xlarge when not actively fingerprinting (~$500/month on-demand when running). Manual starts were the workflow. The intended auto-trigger — `t2s-instance-manager-prod-t2sInstanceManager` Lambda → `ec2:StartInstances` — was written but never wired up (see T2 below).

---

### T2. New AD tracks uploaded to S3 never get fingerprinted

**Symptom:** Admin uploads a new AD track MP3 to `s3://shazacin-t2s/audio-tracks-to-process/{titleId}.mp3`. Hours later, the Title record's `fingerprintingProgress` is still 0 and T2S matching against the new content fails.

**Cause:** This is a **known broken pipeline** in the reference deployment. The intended chain was:

```
S3 PutObject → EventBridge rule "t2s-fingerprinterV2-audiofileupload-rule"
   → t2s-fingerprinter-starter-prod-startFingerprinter Lambda
   → ecs:UpdateService desiredCount=1 on t2s-fingerprinter cluster
```

But the `t2s-fingerprinter` **ECS cluster is a stub** — no task definition, 0 running tasks. The `UpdateService` call is a **no-op**. Meanwhile, the lambda that was supposed to actually start the EC2 fingerprinter (`t2s-instance-manager-prod-t2sInstanceManager`) has **no wired trigger** — no EventBridge rule targets it, no CloudWatch alarm invokes it, no schedule runs it.

**Diagnostic:**
```bash
# Confirm the EventBridge rule exists and is enabled
aws events list-rules --region eu-west-1 --name-prefix t2s-fingerprinterV2

# Confirm the fingerprinter ECS cluster has no tasks
aws ecs list-tasks --cluster t2s-fingerprinter --region eu-west-1
# Expect: EMPTY

# Confirm the instance-manager Lambda has no triggers
aws lambda list-event-source-mappings --function-name t2s-instance-manager-prod-t2sInstanceManager --region eu-west-1
aws events list-rule-names-by-target --target-arn arn:aws:lambda:eu-west-1:400650000765:function:t2s-instance-manager-prod-t2sInstanceManager --region eu-west-1
# Expect: EMPTY for both
```

**Fix (pick one):**

**Option A — manual (the current reference workflow):**
```bash
aws ec2 start-instances --instance-ids i-04821c5781bfa4471 --region eu-west-1
# SSH in (you'll need the key pair — SSM won't work, no instance profile)
# Run the fingerprinter process manually against the new audio
# Stop the instance when done (cost!)
aws ec2 stop-instances --instance-ids i-04821c5781bfa4471 --region eu-west-1
```

**Option B — wire up the intended auto-trigger (recommended for fresh deployments):**
Create an EventBridge rule that invokes `t2s-instance-manager-prod-t2sInstanceManager` on the same S3 PutObject pattern:
```bash
# Use the same event pattern as the existing (broken) rule
aws events put-rule --name t2s-instance-manager-trigger \
  --event-pattern '{
    "source": ["aws.s3"],
    "detail-type": ["Object Created (PutObject)"],
    "detail": {
      "bucket": {"name": ["shazacin-t2s"]},
      "object": {"key": [{"prefix": "audio-tracks-to-process/"}]}
    }
  }' --region eu-west-1

aws lambda add-permission --function-name t2s-instance-manager-prod-t2sInstanceManager \
  --statement-id t2s-instance-manager-eventbridge \
  --action lambda:InvokeFunction --principal events.amazonaws.com --region eu-west-1

aws events put-targets --rule t2s-instance-manager-trigger \
  --targets '{"Id":"1","Arn":"arn:aws:lambda:eu-west-1:400650000765:function:t2s-instance-manager-prod-t2sInstanceManager"}' --region eu-west-1
```

**Why this happens:** The fingerprinter pipeline was originally designed around an ECS Fargate service that was supposed to scale from 0→1 on S3 event. The team later switched the fingerprinter to plain EC2 (cheaper for bursty workloads) but never updated the trigger chain. The `t2s-fingerprinter-starter` lambda still calls the old (empty) ECS cluster.

---

### T3. ALB health checks fail on the T2S checker

**Symptom:** The T2S checker ECS task keeps getting killed by the ALB — health checks fail, the task is marked unhealthy, ECS restarts it, the cycle repeats.

**Cause:** The T2S checker listens on **port 8001**. If your health check path is wrong (`/health` instead of `/`, for example) or the port is wrong (the reference ALB is `t2s-c-LoadB-WKQV4N4D6SE8-f1789f87fcb317c5.elb.eu-west-1.amazonaws.com:8001`), the ALB sees the task as unhealthy.

**Diagnostic:**
```bash
# Describe the target group's health check config
aws elbv2 describe-target-groups --region eu-west-1 --query 'TargetGroups[?contains(TargetGroupArn, `t2s-checker`)].{Protocol:Protocol,Port:Port,Path:HealthCheckPath,Interval:HealthCheckIntervalSeconds,Timeout:HealthCheckTimeoutSeconds,Threshold:HealthyThresholdCount}' --output table

# Check actual health of the targets
aws elbv2 describe-target-health --target-group-arn TARGET_GROUP_ARN --region eu-west-1
```

**Fix:** Set the health check path to `/` (the Dejavu matcher's root responds with `200 OK` by default), port to `8001`, and increase the timeout to 10s (cold-start of the hash DB load can take 5–8s).

**Why this happens:** The Dejavu matcher doesn't expose a `/health` endpoint by default — it only has the `/sync` (POST) and `/` (GET) endpoints. If you add a `/health` endpoint to your matcher, set it as the health check path; otherwise use `/`.

---

### T4. Dejavu database missing — matcher starts but every query returns "no match"

**Symptom:** The T2S checker container starts cleanly, the ALB shows it as healthy, but every `/t2s/sync` request returns `{"match": null, "closest_matches": []}` regardless of what audio you send.

**Cause:** The Dejavu hash database is missing or empty. In the reference deployment, the **checker bakes the hash DB into the container image itself** (885MB image, last pushed 2022-03). If you build a fresh image without the DB, or the DB file is corrupt, you get this symptom.

**Diagnostic (inside the container):**
```bash
# Exec into a running checker task
aws ecs execute-command --cluster t2s-checker --task TASK_ID --container t2s-checker --interactive --command "/bin/bash" --region eu-west-1
# Inside the container:
ls -lah /app/fingerprints/
python -c "from dejavu import Dejavu; djv = Dejavu({'database': {'host': 'localhost', 'user': 'root', 'password': '', 'name': 'dejavu'}}); print(djv.db.get_fingerprinted_songs())"
```

**Fix:** Either:
1. Re-build the container image with a known-good hash DB in `/app/fingerprints/`.
2. Point the matcher at a separate hash DB service (Redis or Postgres) and load it from a snapshot. See [`04-t2s-sync-engine.md` §"Hash database"](04-t2s-sync-engine.md) for the schema.

**Why this happens:** Hash DB sync between the fingerprinter (which writes new hashes) and the checker (which reads them) is the **most fragile part of the architecture**. The reference deployment has no sync mechanism — the checker's DB is a snapshot baked at image build time. To refresh the checker's DB, you must rebuild the image. This is a known operational gap.

---

### T5. The `audio-transcoder` Lambda times out on large WebM files

**Symptom:** CloudWatch logs for `audio-transcoder-prod-transcodeAndExposeAudioDescriptiveTracks` show `Task timed out after 360.00 seconds` when processing a >500MB WebM file.

**Cause:** The transcoder uses bundled `/opt/ffmpeg/ffmpeg` (Lambda layer) and runs in 2048MB memory with a 360s timeout. Large files exceed this.

**Fix:** Three options, in increasing complexity:
1. **Pre-split large files** before upload (most pragmatic).
2. **Bump the timeout to 900s** (Lambda max) — but at 2048MB memory, this costs more.
3. **Migrate transcoding to ECS Fargate** — trigger a Fargate task via S3 → EventBridge → Lambda, run ffmpeg on a 4 vCPU/8GB task that processes the file and writes to `shazacin-static-content`. This is the right answer for production.

---

## Firebase / Push Notification Issues

### F1. FCM token registration returns 403 Forbidden

**Symptom:** The PWA calls `POST /register` to register the FCM token, and the API returns `403` with no useful body.

**Cause:** The `/register` endpoint is protected by a **Cognito user pool authorizer**. The request must include a valid `Authorization: Bearer <JWT>` header. If the JWT is expired, missing, or from the wrong user pool, you get 403.

**Diagnostic:**
```bash
# Test the endpoint with a known-good JWT (extract from the PWA's auth state)
curl -X POST https://5iub6lxbcf.execute-api.eu-west-1.amazonaws.com/prod/register \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"userId":"test-user","deviceToken":"fake-token","platform":"web"}' \
  -v
```

**Fix:** Refresh the JWT before calling `/register`. If the JWT is valid but you still get 403, check that the authorizer's user pool ID matches your deployed pool — the reference authorizer is wired to the app pool (`eu-west-1_gdo3NUHbn`).

---

### F2. Service worker not activating — `navigator.serviceWorker.ready` never resolves

**Symptom:** The PWA's `Notification.requestPermission()` succeeds, but the service worker never activates. `navigator.serviceWorker.ready` hangs indefinitely. No FCM token is generated.

**Cause:** The service worker file (`sw.js` or `sw.ts`) is served with the wrong MIME type or is missing the `type: 'module'` flag. The reference deployment's `src/sw.ts` uses `importScripts()` to load the Firebase compat SDK — this requires the worker to be a classic worker, not a module worker.

**Diagnostic:**
```js
// In the browser console:
navigator.serviceWorker.getRegistrations().then(r => console.log(r));
// If empty, the SW never registered. Check the registration call:
navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(r => console.log(r));
// Look for errors in the Application → Service Workers tab in DevTools
```

**Fix:** Ensure `sw.js` is at the root of your PWA's deploy directory, served with `Content-Type: text/javascript`, and registered without `{ type: 'module' }`. The `importScripts()` API is only available in classic workers, not module workers.

**Why this happens:** Vite and other modern bundlers default to module workers (`{ type: 'module' }`). The reference deployment's SW uses `importScripts()` (a classic worker API) because it's required for Firebase compat SDK loading. If Vite bundles your SW as a module worker, `importScripts` is undefined and the SW fails to install.

---

### F3. iOS PWA push silently fails — token never registers

**Symptom:** On Android and desktop Chrome, push works perfectly. On iOS Safari (PWA installed to home screen), the user grants permission but no FCM token is ever registered.

**Cause:** iOS Safari push has several quirks that don't apply to other platforms:

1. **iOS 16.4+ is required.** Older versions silently fail (no error, no token, no permission state change).
2. **The PWA must be installed to the home screen.** iOS push does not work in browser tabs — only in the home-screen PWA context.
3. **The Firebase Messaging SDK must be loaded in the service worker context, not the main thread.** If the SW only does `postMessage` to the main thread which then calls FCM, iOS doesn't get the token.

**Diagnostic:** On an iOS device (not simulator — simulators can't test push):
1. Check iOS version: Settings → General → About → Software Version. Must be ≥ 16.4.
2. Check the PWA is installed to home screen (Safari → Share → Add to Home Screen).
3. Open the PWA from the home screen icon, not Safari.
4. In the PWA, open the Web Inspector (Safari → Develop → [device] → [PWA]). Look for SW errors in the console.

**Fix:**
- Add an iOS version check to your onboarding flow and surface a "Push notifications require iOS 16.4+" message to users on older versions.
- Ensure the SW calls `firebase.messaging()` directly, not via `postMessage` to the main thread.
- Always `await navigator.serviceWorker.ready` before requesting a token — the SW must be active first.

**Why this happens:** Apple's PWA push implementation requires the SW to be the FCM client, because iOS routes push through APNs (not FCM's direct connection). The SW is the only context where the browser can receive APNs-style messages.

---

### F4. `firebase-admin` SDK fails to initialise in the Lambda

**Symptom:** `combined_lambda` CloudWatch logs show `Error: Failed to parse private key: Error: error:0909006C:PEM routines:get_name:no start line`.

**Cause:** The `FIREBASE_PRIVATE_KEY` environment variable has lost its newlines. When you paste a Firebase service account JSON's `private_key` into an AWS Lambda env var via the Console, the Console strips newlines. The key is multi-line PEM — newlines are required.

**Fix:** Set the env var with explicit newlines. Either:
1. Use `aws lambda update-function-configuration --environment "Variables={FIREBASE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n}"` (the `\n` are literal escape sequences).
2. Or store the key in AWS Secrets Manager and load it at cold start, avoiding env var entirely. (This is the recommended approach.)

**Reference:** The reference deployment stores `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, and `FIREBASE_PRIVATE_KEY` as Lambda env vars on `combined_lambda`. **These are the only secrets in the entire backend.** When publishing your own deployment, redact them from any committed config — see `00-inventory.md §17` in the reference docs.

---

## Admin Portal Issues

### A1. Admin signup fails with "Invalid email domain"

**Symptom:** A new admin user tries to sign up with `admin@your-org.com` and the signup is rejected with `Invalid email domain: your-org.com`.

**Cause:** The admin pool's PreSignUp Lambda (`shazacinadminportal1c4973ffPreSignup-dev` in the reference deployment) reads the `DOMAINWHITELIST` env var and rejects any email whose domain isn't on the list. The reference value is:

```
DOMAINWHITELIST=shazacin.com, ghi.ngo
```

If your organisation's domain isn't in that list, signup is blocked.

**Diagnostic:**
```bash
aws lambda get-function-configuration --function-name shazacinadminportal1c4973ffPreSignup-dev --region eu-west-1 --query 'Environment.Variables' --output table
```

**Fix:** Update the env var with your domains:
```bash
aws lambda update-function-configuration --function-name shazacinadminportal1c4973ffPreSignup-dev --region eu-west-1 \
  --environment 'Variables={DOMAINBLACKLIST=,DOMAINWHITELIST=your-org.com,partners.org,ENV=dev,MODULES=email-filter-whitelist,REGION=eu-west-1}'
```

**The PreSignUp logic** (from the reference deployment's `email-filter-whitelist.js`):
```javascript
exports.handler = (event, context, callback) => {
  const wld = process.env.DOMAINWHITELIST.split(',').map(d => d.trim());
  const { email } = event.request.userAttributes;
  const domain = email.substring(email.indexOf('@') + 1);
  if (!wld.includes(domain)) {
    callback(new Error(`Invalid email domain: ${domain}`), event);
  } else {
    callback(null, event);
  }
};
```

**Why this happens:** The admin portal uses domain-based allowlisting, not per-user allowlisting. This is intentional — it's simpler to maintain than a per-user list. The trade-off is that anyone with an `@your-org.com` email can sign up, so the domain must be tightly controlled (e.g. only issued to actual admins).

---

### A2. CustomMessage lambda sends a confirmation email with the wrong redirect URL

**Symptom:** A new admin signs up, gets the confirmation email, clicks the link, and lands on `http://localhost:8080/oauth2/idpresponse` — which doesn't exist in production.

**Cause:** The CustomMessage Lambda (`shazacinadminportal1c4973ffCustomMessage-dev`) has `REDIRECTURL=http://localhost:8080/oauth2/idpresponse` baked into its env vars. This is a dev-only setting.

**Fix:** Update the env var:
```bash
aws lambda update-function-configuration --function-name shazacinadminportal1c4973ffCustomMessage-dev --region eu-west-1 \
  --environment 'Variables={EMAILMESSAGE=Please confirm your email address for the DescribeAT Administration Portal,EMAILSUBJECT=NO-REPLY | Confirm your email — DescribeAT Admin,REDIRECTURL=https://admin.your-domain/oauth2/idpresponse,RESOURCENAME=shazacinadminportal1c4973ffCustomMessage}'
```

**While you're here:** The reference deployment also has a typo in `EMAILSUBJECT` (`Administartion` instead of `Administration`). Fix that too.

---

### A3. AppSync admin mutations return "Cannot resolve type" errors

**Symptom:** The admin portal calls a mutation like `createShazacinMetadataTitles` and gets `Cannot resolve type 'ShazacinMetadataTitles'` from AppSync.

**Cause:** AppSync's resolver for the mutation isn't wired up. The reference deployment's admin AppSync API (`4btq2hqzbrbqbczbqtmufmauha`) has resolvers for each type, but if you recreated the API from `schema.graphql` without running `amplify push` (which auto-generates resolvers), the resolvers are missing.

**Diagnostic:**
```bash
# List resolvers for the admin API
aws appsync list-resolvers --api-id 4btq2hqzbrbqbczbqtmufmauha --type-name ShazacinMetadataTitles --region eu-west-1
# Expect resolvers for createShazacinMetadataTitles, updateShazacinMetadataTitles, deleteShazacinMetadataTitles, listShazacinMetadataTitles, getShazacinMetadataTitles
```

**Fix:** For each type, create resolvers that map the GraphQL operation to a DynamoDB data source. The easiest path is to re-run `amplify push` from the admin Amplify project — it regenerates all resolvers from the schema.

If you're not using Amplify, you must manually create resolvers using the DynamoDB data source name (`shazacin_title_meta_db`, `shazacin_metadata_ad_tracks`, etc. — see [`00-inventory.md §4.1`](https://example.com/inventory) for the full mapping).

---

### A4. `listAdminUsers` query returns 500 with no useful error

**Symptom:** The admin portal's "Manage users" page fails to load. CloudWatch logs for `shazacin-admin-cognito-users` Lambda show `Task timed out after 3 seconds`.

**Cause:** The `listAdminUsers` resolver is a Lambda (`shazacin-admin-cognito-users`, 128MB memory, 3s timeout) that calls Cognito's `ListUsers` API. For pools with many users, this call takes longer than 3s — especially across regions (if the Lambda is in `eu-west-1` but the pool is in `us-east-1`).

**Fix:**
1. Increase the timeout to 10s: `aws lambda update-function-configuration --function-name shazacin-admin-cognito-users --timeout 10 --region eu-west-1`.
2. Increase memory to 256MB (Cognito calls are CPU-bound in the SDK; more memory = more CPU).
3. If the pool has thousands of users, paginate — don't return all in one call. Cognito's `ListUsers` supports `Limit` and `PaginationToken`.

---

## Data Model Issues

### DM1. The `shazacin-metadata-categories` table has no GraphQL resolver

**Symptom:** You query `listShazacinMetadataCategories` via the admin AppSync API and get `Cannot resolve type 'ShazacinMetadataCategories'`. But the DynamoDB table exists and has data.

**Cause:** This is a **known gap in the reference deployment**. The `shazacin-metadata-categories` table is **not documented in `schema.graphql`** and has **no AppSync resolver** — neither in the admin API nor the SAM App API. The admin UI accesses categories via a Lambda (likely `combined_lambda` or another path) or directly via the AWS SDK.

**Diagnostic:**
```bash
# Confirm the table exists
aws dynamodb describe-table --table-name shazacin-metadata-categories --region eu-west-1 --query 'Table.{Name:TableName,ItemCount:ItemCount,KeySchema:KeySchema}' --output table

# Confirm no resolver exists
aws appsync list-resolvers --api-id 4btq2hqzbrbqbczbqtmufmauha --type-name ShazacinMetadataCategories --region eu-west-1
# Expect: empty
```

**Fix (pick one):**
1. **Add a resolver manually** — create a DynamoDB data source for `shazacin-metadata-categories` and wire up the standard CRUD resolvers. Add the type to `schema.graphql`.
2. **Migrate to Amplify-managed** — add a `@model` directive for categories in the admin Amplify project's `schema.graphql`, map it to the existing table via `@model(tableName: "shazacin-metadata-categories")`, run `amplify push`.
3. **Accept the gap** — if the admin UI's category access is via Lambda and works fine, leave it as-is. But document the access pattern in the schema so future contributors don't waste time looking for the resolver.

**Why this happens:** The categories table was likely added after the initial Amplify push, in a way that bypassed Amplify's GraphQL transform — possibly via the Console or a one-off script. It's an undocumented entity in the schema.

---

### DM2. Orphaned `ShazacinStack-dev-*` tables cluttering the DynamoDB console

**Symptom:** Your DynamoDB console shows 10 tables with names like `ShazacinStack-dev-devDescribeAtADtracksMetadataC8BE2A27-9DG0X8LDVVOG`. None are referenced by production code.

**Cause:** These are **CloudFormation stack remnants from deleted dev environments**. Each `-dev` in the name indicates a dev stack; the duplicate `-XX...YY` hash suffixes come from multiple deploys of the same stack. They're orphaned — no production code references them.

**Fix:**
```bash
# List all dev-prefixed tables
aws dynamodb list-tables --region eu-west-1 --query 'TableNames[?starts_with(@, `ShazacinStack-dev-`)]' --output table

# Delete each one (they're on-demand, no read/write activity, so deletion is safe)
for TABLE in $(aws dynamodb list-tables --region eu-west-1 --query 'TableNames[?starts_with(@, `ShazacinStack-dev-`)]' --output text); do
  echo "Deleting $TABLE..."
  aws dynamodb delete-table --table-name "$TABLE" --region eu-west-1
done
```

**Cost impact:** On-demand DynamoDB tables cost ~$0 when idle (you pay per read/write). Deleting them saves console clutter, not money. But they're confusing for new contributors who see 17 tables and don't know which 7 are prod.

---

### DM3. The feedback resolver's data source name is misleading

**Symptom:** You're debugging an AppSync resolver for `UserFeedback` and the data source name is `shaza_user_notifs_incoming_ds` — which sounds like it should be wired to incoming notifications, not feedback.

**Cause:** This is a **known naming mismatch** in the reference deployment. The Admin API's data source `shaza_user_notifs_incoming_ds` is mapped to feedback resolvers, not incoming notifications. The SAM App API correctly names it `shazacin_user_feedback`.

**Fix:** No functional fix needed — the resolver works despite the misleading name. But when you create your own deployment, use the SAM App's naming (`shazacin_user_feedback`) and avoid the confusion.

---

### DM4. GraphQL queries fail with "field not found" after a schema change

**Symptom:** A client queries `score` on a Title, and AppSync returns `Cannot resolve type field 'score'`.

**Cause:** **Schema drift** — the schema was updated to remove `score`, but existing data rows still have it. Or the schema was updated to add `score`, but old data rows don't have it.

**Fix:** See the [Schema drift section in `03-data-model.md`](03-data-model.md) for the full mitigation playbook. The short version:
- For fields in data but not schema: either add them to the schema (if useful) or migrate the data to remove them.
- For fields in schema but not data: populate them or make them optional.
- Never delete a schema field without first checking that no data uses it.

---

## Cost Issues

### C1. Unexpected $500 AWS charge — the EC2 fingerprinter was left running

**Symptom:** Your monthly AWS bill spikes by ~$500 and you don't know why.

**Cause:** The T2S fingerprinter EC2 instance is an **r5.4xlarge** (16 vCPU / 128 GB RAM). On-demand pricing in `eu-west-1` is ~$1.008/hour → **~$726/month** if left running 24/7. With a 1-year reservation, ~$200/month. The instance is meant to be **stopped when not actively fingerprinting**, but if you forget to stop it after a fingerprinting session, it stays running.

**Diagnostic:**
```bash
# Check the instance state
aws ec2 describe-instances --instance-ids i-04821c5781bfa4471 --region eu-west-1 --query 'Reservations[0].Instances[0].State.Name' --output text

# Check how long it's been running (uptime)
aws ec2 describe-instances --instance-ids i-04821c5781bfa4471 --region eu-west-1 --query 'Reservations[0].Instances[0].LaunchTime' --output text

# Get cost breakdown by service for the last month
aws ce get-cost-and-usage --time-period Start=2026-06-01,End=2026-07-01 --granularity MONTHLY --metrics BlendedCost --group-by Type=DIMENSION,Key=SERVICE --region us-east-1
```

**Fix:**
1. Stop the instance now: `aws ec2 stop-instances --instance-ids i-04821c5781bfa4471 --region eu-west-1`.
2. Set up a **scheduled auto-stop** — a CloudWatch Events rule that runs daily at 22:00 and stops the instance if it's running. (The reference deployment has something similar for `shaza-n8ai-instance` via EventBridge Schedules `Start-EC2-Morning` / `Stop-EC2-Evening`.)
3. For long-term cost reduction, consider migrating the fingerprinter to **ECS Fargate** (truly scale-to-zero, no instance left running) or **Spot Instance** pricing (70% discount, but interruptible).

**Why this happens:** The cost-saving strategy of stopping the EC2 only works if you actually stop it. The reference deployment's auto-stop mechanism is for a different instance (`shaza-n8ai-instance`, the n8n workflow box) — there's no equivalent auto-stop for the fingerprinter EC2. Manual stop is the workflow, and humans forget.

---

### C2. DynamoDB capacity alarms firing constantly

**Symptom:** You receive CloudWatch alarm emails like `shazacin-metadata-titles-ReadCapacityUnitsLimit-BasicAlarm`.

**Cause:** The reference deployment has **14 CloudWatch alarms**, all DynamoDB capacity alarms auto-generated by Amplify. They fire when consumed read/write capacity exceeds the table's provisioned limit. If you're on **on-demand** billing mode, these alarms are spurious — on-demand has no hard limit, only soft throttling.

**Diagnostic:**
```bash
# Check the table's billing mode
aws dynamodb describe-table --table-name shazacin-metadata-titles --region eu-west-1 --query 'Table.BillingModeSummary.BillingMode' --output text

# List all DynamoDB capacity alarms
aws cloudwatch describe-alarms --alarm-name-prefix shazacin --region eu-west-1 --query 'MetricAlarms[?contains(AlarmName, `CapacityUnitsLimit`)].AlarmName' --output table
```

**Fix:** If your tables are on-demand, delete the alarms:
```bash
for ALARM in $(aws cloudwatch describe-alarms --alarm-name-prefix shazacin --region eu-west-1 --query 'MetricAlarms[?contains(AlarmName, `CapacityUnitsLimit`)].AlarmName' --output text); do
  aws cloudwatch delete-alarms --alarm-names "$ALARM" --region eu-west-1
done
```

If you're on provisioned capacity, either raise the limit or switch to on-demand (simpler, only slightly more expensive at low volume).

---

### C3. Total monthly cost higher than the docs estimate

**Symptom:** Your monthly AWS bill is $80, not the "$35/month idle" the cost docs estimate.

**Cause:** The cost estimate in [`08-cost-estimates.md`](08-cost-estimates.md) assumes:
- t2s-checker Fargate running 24/7 (~$12)
- ALB (~$20)
- t2s-fingerprinter EC2 **stopped** ($0)
- Route53 private zones (<$1)
- S3 + SQS (~$1)
- Supporting Lambdas idle (<$1)

If your fingerprinter EC2 is running, that alone adds ~$500/month on-demand. If you have multiple CloudFront distributions (the reference has 6), each adds ~$1/month base + per-request costs. If you're running dev environments in parallel, those add up.

**Fix:**
1. Audit running resources: `aws resourcegroupstaggingapi get-resources --region eu-west-1 --output table`.
2. Stop any non-prod EC2 instances.
3. Delete orphaned CloudFront distributions (the reference has festival demos and dev distributions that may be stale).
4. Delete orphaned DynamoDB tables (see DM2).
5. Re-run the cost estimate with your actual usage.

---

## FAQ

### General

**Q1. What is DescribeAT, in one sentence?**

DescribeAT is an accessibility platform that lets blind and visually impaired users hear audio-described versions of movies and TV shows while watching them in real time — they record a few seconds of ambient audio, the system identifies what they're watching, and plays the matching audio description track synced to their current position.

---

**Q2. Is this a SaaS or a self-hostable project?**

Both. The reference deployment is a SaaS (currently live at `app.shazacin.com`), but the open-source release is designed to be self-hostable — any organisation can deploy their own instance with their own catalogue, their own admin portal, and their own branding. The [Deploy Your Own guide](07-deploy-your-own.md) walks through the 8-step process.

---

**Q3. Why is the AppSync API key committed to `aws-exports.ts`?**

This is a known security weakness in the reference deployment. AppSync API keys are **not** bearer tokens for user data — they authorise the API itself, not the user. User-scoped authorisation (whose feedback can this user read?) is enforced by Cognito user pool JWT auth layered on top. The API key being committed means anyone can query the public API, but they can't read another user's private data without a valid JWT.

That said, exposing the API key allows unauthenticated abuse of public queries (e.g. scraping the catalogue). The recommended fix is to move the API key out of `aws-exports.ts` into a runtime config, or switch the default auth mode to Cognito user pool (requiring all clients to sign in).

---

**Q4. Can I use a non-AWS backend (Auth0, Hasura, Cloudflare)?**

Yes. The architecture is cloud-agnostic. The data layer supports AppSync (AWS), Hasura + Postgres (portable), or custom GraphQL servers. The auth layer supports Cognito, Auth0, Keycloak, or Clerk. See the [Deploy Your Own guide](07-deploy-your-own.md) for the trade-offs of each option. The T2S sync engine is the most AWS-tied piece (uses ECS + ALB + EC2), but it can be replaced with any containerised HTTP service.

---

### Setup

**Q5. Do I need Amplify CLI, or can I use CDK?**

You need **both**, in different places. The reference deployment's auth (Cognito pools), data layer (AppSync APIs + DynamoDB tables), and hosting (Amplify Hosting for the frontend) were all created by `amplify push`. CDK was used only for the push token registration endpoint (`NotificationsApiStack.ts`, 56 lines). If you're starting fresh, you can do everything in CDK, but you'll write 200+ lines per Cognito pool, 500+ lines per AppSync API with resolvers, etc. — Amplify handles all of that for you. See [Deployment Issue D2](#d2-amplify-vs-cdk--which-one-should-i-use) for the full recommendation.

---

**Q6. Can I deploy to a region other than `eu-west-1`?**

Yes. The architecture is region-agnostic. Just ensure:
- All your resources are in the same region (Cognito pools, AppSync APIs, DynamoDB tables, Lambda functions, EC2 instances, ECS clusters, S3 buckets).
- ACM certificates for CloudFront custom domains are in `us-east-1` (CloudFront requires this, regardless of where your origins live — see [D1](#d1-cloudfront-distribution-stuck-in-inprogress-for-over-an-hour)).
- The service worker's Firebase config (`firebase.json`) points at your Firebase project (which is global, not region-scoped).

---

**Q7. What's the minimum AWS permissions I need to deploy DescribeAT?**

You need an IAM role (or user with access keys) that can:
- Create Cognito user pools, clients, and domains
- Create AppSync GraphQL APIs and resolvers
- Create DynamoDB tables
- Create Lambda functions and layers
- Create S3 buckets and set CORS / notification configs
- Create CloudFront distributions and origin access identities
- Create ACM certificates (in `us-east-1`)
- Create Route53 records (if you're using Route53)
- Create ECS clusters, task definitions, and services
- Create EC2 instances and security groups
- Create ALBs and target groups
- Create EventBridge rules and Lambda event source mappings
- Create API Gateway REST APIs

In practice, this is `AdministratorAccess` for the deploy account. For ongoing operations, you can scope down to read + specific write permissions, but the deploy step is broad.

---

### T2S Engine

**Q8. Do I have to use Dejavu, or can I use a different fingerprinting engine?**

You can use any fingerprinting engine that exposes an HTTP endpoint accepting `audio/mpeg` POST and returning `{ song_id, song_name, offset_seconds, input_confidence }`. The reference deployment used a commercial closed-source library; Dejavu is the open-source default. See [`04-t2s-sync-engine.md` §"Choosing your fingerprinting engine"](04-t2s-sync-engine.md) for the three options.

---

**Q9. Why is the fingerprinter an EC2 instance and not ECS Fargate?**

The original design called for an ECS Fargate service that scales 0→1 on S3 event. The team later switched to plain EC2 because:
- **Bursty workload**: fingerprinting is rare (new uploads), heavy when it happens (4+ vCPU, lots of I/O). Fargate's 30s cold start + per-vCPU pricing made it more expensive than EC2 for this pattern.
- **Local hash DB storage**: the fingerprinter writes new hashes to a local EBS volume (8GB gp2). With Fargate, you'd need EFS for persistent storage, adding cost and complexity.
- **Cost control**: an EC2 r5.4xlarge stopped costs $0. When running, it's ~$500/month on-demand — but if you only run it for a few hours per fingerprinting session, the monthly cost is $5-20, not $500.

The trade-off is that the auto-trigger pipeline (S3 → Lambda → EC2 start) is more fragile than S3 → Lambda → ECS task start. See [T2](#t2-new-ad-tracks-uploaded-to-s3-never-get-fingerprinted) for the known broken pipeline.

---

**Q10. The hash DB is "baked into the container image" — what does that mean for updates?**

In the reference deployment, the T2S checker's hash DB is in the 885MB container image (last pushed 2022-03). To update the checker's hash DB, you must:
1. Build a new container image with the updated hash DB.
2. Push the image to ECR.
3. Force a new deployment of the ECS task: `aws ecs update-service --service t2s-checker --force-new-deployment --cluster t2s-checker --region eu-west-1`.

This is a known operational fragility. The recommended improvement is to move the hash DB to a separate storage (S3, EFS, or a Postgres instance) and have the checker load it at task startup. This decouples DB updates from image rebuilds.

---

**Q11. What's the `song_id → titleId` mapping problem?**

The T2S matcher returns `{ song_id: 42, song_name: "2b237778-288a-4b05-b075-798804d26537" }`. The `song_id` is an internal Dejavu integer; the `song_name` is the original filename (which happens to be the titleId UUID). The client needs to extract the titleId from `song_name` and look up the AD Track for that title.

In the reference deployment, **this mapping was never implemented in the client** — both v2 and v3 SPAs use hardcoded mock data for `song_id` and never make real T2S calls. For your deployment, you must:
1. Parse `song_name` to extract the titleId (it's `{titleId}.mp3` or just `{titleId}`).
2. Query the data layer for the title's AD tracks.
3. Filter by the user's language preference.
4. Start playback at `offset_seconds`.

This is a critical implementation gap that new deployers must fill. See [`05-discoveries.md` §4](https://example.com/discoveries) in the reference docs for the full investigation.

---

### Firebase / Push

**Q12. Do I need Firebase, or can I use a different push provider?**

Firebase Cloud Messaging (FCM) is the cross-platform push provider used by the reference deployment. It's free for unlimited messages and handles both web (Chrome, Firefox, Edge) and iOS Safari push (via APNs).

Alternatives:
- **OneSignal** — easier setup, but adds a third-party dependency and per-user pricing at scale.
- **Direct APNs + Web Push** — no Firebase dependency, but you manage two code paths (iOS and web) and lose FCM's unified API.
- **Amazon SNS** — AWS-native, but the web push story is weaker than FCM.

For most self-hosters, FCM is the path of least resistance. If you want to stay fully AWS-native, you can use Amazon SNS + ADM (Android) + APNs (iOS) + Web Push API (browsers), but you'll write more integration code.

---

**Q13. Why is the Firebase config (API key, VAPID key) safe to publish?**

The Firebase web config (`apiKey`, `projectId`, `messagingSenderId`, `appId`) and VAPID key are **client-side by design** — they're published in your web app's JavaScript and visible to any user who opens DevTools. They are not secrets. Firebase's security model is:

- The API key identifies your project, doesn't grant access to anything.
- The VAPID key is the public half of a key pair used for web push subscription.
- User data access is controlled by Firebase Security Rules (Firestore, Realtime DB) or by your backend's own auth (Cognito JWT in DescribeAT's case).

The **only** Firebase secret is the Admin SDK private key, which lives in the `combined_lambda` env vars (`FIREBASE_PRIVATE_KEY`) and must never be committed. See [F4](#f4-firebase-admin-sdk-fails-to-initialise-in-the-lambda).

---

### Admin Portal

**Q14. How do I add a new admin user?**

1. The admin signup is **domain-allowlisted** — anyone with an email at `@your-org.com` (or whatever domains are in `DOMAINWHITELIST`) can sign up at the admin portal's sign-up page.
2. The new user must confirm their email (the CustomMessage Lambda sends a confirmation link).
3. Once confirmed, the user can sign in to the admin portal.

There is no per-user allowlist, no MFA enforcement, and no admin approval step. If you need tighter control, modify the PreSignUp Lambda to check a per-user allowlist (stored in DynamoDB) or require MFA via Cognito's built-in MFA settings.

---

**Q15. Why does the admin portal use a separate Cognito pool from the listener app?**

The admin pool (`shazacin-admin-portal`) and the app pool (`appfrontend03c6cece`) are separate because they have **different access patterns**:
- The app pool has thousands of listeners (open signup, no domain restriction).
- The admin pool has a handful of admins (closed signup, domain-allowlisted).
- The admin pool has a CustomMessage trigger (custom confirmation email with admin portal branding).
- The admin pool's JWT scopes authorise admin-only AppSync mutations; the app pool's JWT scopes authorise listener-only queries.

Putting them in the same pool would require complex per-user authorisation logic. Two pools is simpler and more secure.

---

### Data Model

**Q16. What's in the `shazacin-user-notifications-incoming` table, and how is it written?**

This table holds **inbound notifications from admin → listener** (the outbox pattern). It's written by the `shazacin-user-notifications-outgoing-sqs-processor` Lambda (which consumes from the SQS queue `shazacin-user-notifications-queue`). The intended reader was `shazacin-user-notifications-incoming-processor`, which would process the DynamoDB stream and send FCM pushes.

In the reference deployment, **this DynamoDB stream trigger was never wired up** — the event source mapping is orphaned (no stream enabled on the table). The live path for push notifications is direct `combined_lambda` → FCM, bypassing this table entirely. The table still receives writes (from the SQS processor), but nothing reads from it. See [`06-notifications.md`](06-notifications.md) for the architecture.

For your own deployment, you can either:
1. Wire up the DynamoDB stream (the "intended" architecture) — enables queue-based, retry-friendly notification delivery.
2. Skip this table entirely and have `combined_lambda` write directly to FCM + the `shazacin-user-notifications` outbox table — simpler, fewer moving parts.

---

**Q17. What's the `fcmTokens` table, and how do I register a token?**

The `fcmTokens` table stores device push tokens per user. It's written via the `fcmTokensAPI` Lambda, which is triggered by `POST /register` on the API Gateway (`NotificationsApiStack`, the only CDK-managed piece of the backend).

To register a token:
```bash
curl -X POST https://5iub6lxbcf.execute-api.eu-west-1.amazonaws.com/prod/register \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"userId":"cognito-sub-xxx","deviceToken":"fcm-token-xxx","platform":"web","userAgent":"Mozilla/5.0..."}'
```

The endpoint requires a valid Cognito JWT (app pool). Without auth, anyone could register a token for any user and receive their notifications.

---

### Cost

**Q18. What's the realistic monthly cost for a small deployment?**

For a deployment with ~100 titles, ~500 listeners, modest T2S usage:
- Cognito: $0 (free tier covers 50,000 monthly active users)
- AppSync: ~$4 (100,000 queries at $4/million)
- DynamoDB (on-demand): ~$5 (modest read/write volume)
- Lambda: ~$2 (modest invocations)
- S3: ~$1 (small catalogue)
- CloudFront: ~$5 (low traffic)
- Route53: ~$1
- T2S checker Fargate (always on): ~$12
- ALB: ~$20
- T2S fingerprinter EC2 (stopped 95% of the time): ~$10 (few hours/month running)
- Firebase: $0 (free tier)

**Total: ~$60/month**. See [`08-cost-estimates.md`](08-cost-estimates.md) for the full breakdown.

---

**Q19. How do I set a budget alert so I don't get surprised by a $500 bill?**

```bash
# Create a monthly budget of $100 with a 50% and 90% alert
aws budgets create-budget \
  --account-id 400650000765 \
  --budget '{
    "BudgetName": "describeat-monthly",
    "BudgetLimit": {"Amount": "100", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST"
  }' \
  --notifications-with-subscribers '[
    {"Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 50}, "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "you@your-org.com"}]},
    {"Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 90}, "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "you@your-org.com"}]}
  ]'
```

Set the threshold to 50% and 90% so you get a warning before you hit the budget cap, not after.

---

### Operations

**Q20. What monitoring is missing in the reference deployment that I should add?**

The reference deployment has **14 CloudWatch alarms, all DynamoDB capacity alarms** (auto-generated by Amplify). It has **no alarms on**:
- T2S ECS clusters (if `t2s-checker` crashes, the service stays at `desired=1, running=0` silently)
- Lambda error rates (`combined_lambda`, `outgoing-sqs-processor`, `audio-transcoder`)
- AppSync 4xx/5xx rates
- EC2 fingerprinter state (running when it shouldn't be)

Recommended additions:
```bash
# Alarm if t2s-checker is unhealthy for >5 min
aws cloudwatch put-metric-alarm --alarm-name t2s-checker-unhealthy \
  --namespace AWS/ECS --metric-name ServiceHealth \
  --dimensions Name=ClusterName,Value=t2s-checker Name=ServiceName,Value=t2s-checker-t2s-checker \
  --statistic Minimum --period 300 --threshold 1 --comparison-operator LessThanThreshold \
  --evaluation-periods 1 --alarm-actions arn:aws:sns:eu-west-1:ACCOUNT:your-alerts

# Alarm if fingerprinter EC2 has been running >4 hours
aws cloudwatch put-metric-alarm --alarm-name t2s-fingerprinter-running-too-long \
  --namespace AWS/EC2 --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-04821c5781bfa4471 \
  --statistic Average --period 300 --threshold 0 --comparison-operator GreaterThanThreshold \
  --evaluation-periods 48 --alarm-actions arn:aws:sns:eu-west-1:ACCOUNT:your-alerts
```

---

**Q21. How do I clean up orphaned resources safely?**

Before deleting anything:
1. Confirm no production code references the resource (grep the repos).
2. Tag the resource as `orphaned` with a date for review.
3. Wait a week. If nothing breaks, delete it.

The reference deployment has ~20 orphaned resources (7 dev Cognito pools, 10 dev DynamoDB tables, 1 test AppSync API, 1 festival CloudFront distribution, 1 one-off Athena bucket). See [`09-orphaned-resources.md`](09-orphaned-resources.md) for the full inventory and cleanup guide.

---

**Q22. Where do I report bugs or contribute fixes?**

Open an issue or PR in the DescribeAT repository. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the contribution guidelines. If you find a bug in the docs (like a wrong resource ID, a stale instruction, or a missing troubleshooting step), the docs are in the same repo — PRs welcome.

---

## Document structure (for maintainers)

| Section | Purpose |
|---|---|
| Common Setup Issues | Issues hit on first contact with the AWS backend (Cognito, AppSync, S3, IAM) |
| Deployment Issues | Issues hit when deploying from scratch (CloudFront, ACM, Amplify vs CDK) |
| T2S Engine Issues | Issues hit when running the fingerprinting engine (EC2, ECS, ALB, Dejavu) |
| Firebase / Push Issues | Issues hit when configuring push notifications (FCM, SW, iOS) |
| Admin Portal Issues | Issues hit when debugging the admin portal (allowlist, resolvers, timeouts) |
| Data Model Issues | Issues hit when the GraphQL data model breaks (missing resolvers, orphans, drift) |
| Cost Issues | Issues hit when the AWS bill is unexpectedly high (EC2, DynamoDB, distributions) |
| FAQ | 22 Q&A items grouped by topic (general, setup, T2S, Firebase, admin, data, cost, ops) |

Each issue follows the format: **Symptom → Cause → Diagnostic command → Fix → Why this happens.** This format is deliberately verbose — when you hit a bug at 2am, the "why this happens" line is what stops you from applying a fix that breaks something else later.

---

## Related docs

- [`00-overview.md`](00-overview.md) — what DescribeAT is and how it's structured
- [`01-architecture.md`](01-architecture.md) — the full system architecture
- [`02-auth.md`](02-auth.md) — the auth model (two Cognito pools)
- [`03-data-model.md`](03-data-model.md) — the four core entities + supporting tables
- [`04-t2s-sync-engine.md`](04-t2s-sync-engine.md) — the fingerprinting engine
- [`05-storage-cdn.md`](05-storage-cdn.md) — where audio and images live
- [`06-notifications.md`](06-notifications.md) — push notifications
- [`07-deploy-your-own.md`](07-deploy-your-own.md) — step-by-step deployment
- [`08-cost-estimates.md`](08-cost-estimates.md) — what to budget
- [`09-orphaned-resources.md`](09-orphaned-resources.md) — keeping your account tidy
- [`10-adrs.md`](10-adrs.md) — why we made the choices we did