# 09 — Orphaned Resources

> How to keep your cloud account tidy, and why it matters.

---

## What are orphaned resources?

An **orphaned resource** is a cloud resource (database table, function, queue, bucket, etc.) that exists in your account but is no longer referenced by any production code. It costs money to keep around, it complicates audits, and it's a security risk (an attacker who compromises an orphaned resource may have a path to your production data).

The original production deployment accumulated **20+ orphaned resources** over its lifetime — tables from a 2020 dev stack, user pools from abandoned experiments, Lambda functions from completed proof-of-concepts. Each one cost a small amount monthly, and together they added up to significant waste. Worse, they made it harder to answer "what does our production environment actually consist of?" — the answer was buried in noise.

---

## How orphans happen

Orphans are not a sign of carelessness. They're a sign of a system that evolved faster than its cleanup processes. The common causes:

1. **Dev/test environments were never deleted.** Someone spun up a dev environment to test a feature, then moved on without tearing it down.
2. **Migrations left the old alongside the new.** A new user pool was created; the old one was never deleted.
3. **Feature flags were removed but the code stayed.** The feature was rolled back, but the Lambda function remained.
4. **Renames.** A resource was renamed (e.g. `prod-titles-table` → `media-titles-table`), but the old name's data was never migrated or deleted.
5. **Backup retention exceeded the backup's purpose.** A backup from 2020 is still around, but no one remembers what it was backing up.

---

## The categories of orphans

### 1. Compute orphans

Lambda functions, ECS services, Fargate tasks, EC2 instances that are no longer invoked.

**How to detect:** Look at CloudWatch metrics. If a function has zero invocations over 30 days, it's an orphan.

**How to clean up:** Tag the function as `orphan-pending`, wait 30 days, then delete.

### 2. Storage orphans

S3 buckets, EBS volumes, EFS file systems that no longer receive writes or reads.

**How to detect:** Look at S3/EBS access logs. If a bucket has zero reads and zero writes over 90 days, it's likely an orphan.

**How to clean up:** Move to a `to-delete` lifecycle policy, then delete after 30 days.

### 3. Database orphans

DynamoDB tables, RDS instances, ElastiCache clusters that are no longer queried.

**How to detect:** Look at CloudWatch metrics. Zero read capacity consumed over 30 days = orphan candidate.

**How to clean up:** Take a snapshot, then delete.

### 4. Auth orphans

Cognito user pools, OAuth clients, IAM roles that are no longer used.

**How to detect:** Look at the auth provider's usage metrics. Zero active users in 30 days = orphan.

**How to clean up:** Export the user list, then delete the pool. Re-create from the export if needed.

### 5. Network orphans

VPCs, subnets, security groups, route tables that are no longer attached to running resources.

**How to detect:** Use the VPC console. Subnets with zero attached resources = orphan.

**How to clean up:** Tag, wait, delete.

---

## The audit checklist

Run this audit quarterly. It takes about 2 hours for a small deployment, longer for a large one.

### Compute
- [ ] List all Lambda functions. Flag those with zero invocations in 30 days.
- [ ] List all ECS services. Flag those with desired count > 0 and zero actual tasks.
- [ ] List all Fargate tasks. Flag stopped tasks older than 7 days.
- [ ] List all EC2 instances. Flag stopped instances older than 30 days.

### Storage
- [ ] List all S3 buckets. For each, check access logs for the last 90 days.
- [ ] List all EBS volumes. Flag those in `available` state (not attached) for >30 days.
- [ ] List all EFS file systems. Flag those with no recent mount activity.

### Database
- [ ] List all DynamoDB tables. For each, check consumed read/write capacity over 30 days.
- [ ] List all RDS instances. Flag those with zero connections over 30 days.
- [ ] List all ElastiCache clusters. Flag those with zero evictions/connections.

### Auth
- [ ] List all Cognito user pools. For each, check the number of active users.
- [ ] List all OAuth clients. Verify each is still referenced by a documented application.
- [ ] List all IAM roles. Verify each has at least one assume-role policy that is recent.

### Network
- [ ] List all VPCs. For each, list subnets and verify each has attached resources.
- [ ] List all security groups. Flag those with no associated ENIs.
- [ ] List all route tables. Verify each is associated with a subnet.

### Other
- [ ] List all SNS topics. Flag those with no subscriptions.
- [ ] List all SQS queues. Flag those with no recent activity.
- [ ] List all API Gateway APIs. Verify each is still referenced by a documented client.
- [ ] List all CloudFront distributions. Verify each has recent traffic.

---

## The deletion process

Once you've identified an orphan, do not delete it immediately. Follow this process:

1. **Tag it as `orphan-pending`.** Use a date tag (`orphan-pending-2026-07-15`).
2. **Take a final backup.** Snapshot or export whatever data is in the orphan.
3. **Wait 30 days.** During this time, monitor for any unexpected access. If something accesses the orphan, investigate before deleting.
4. **Delete.** Remove the resource.
5. **Verify cost reduction.** Check the cost explorer the next billing cycle to confirm the resource is gone and the cost is reduced.

The 30-day wait is not bureaucracy. It's the buffer that catches the case where someone forgot to migrate a dependency to the new resource. Deleting an actively-used resource causes an outage; the 30-day wait makes that visible before the deletion.

---

## The naming convention

The best way to prevent orphans is to make them easy to identify. Adopt a naming convention that includes:

- **Environment:** `prod`, `staging`, `dev`
- **Owner:** The team or person responsible
- **Purpose:** A short description
- **Status:** `active`, `deprecated`, `orphan-pending`

Example:
```
prod-matcher-always-on-active
prod-fingerprinter-on-demand-active
dev-test-feature-x-deprecated
dev-old-cognito-pool-orphan-pending-2026-07-15
```

If a resource's name includes `deprecated` or `orphan-pending`, treat it as a deletion candidate. If it includes neither, it's expected to be in active use.

---

## The monthly review

Once a month, walk through the resources created in the last 30 days. For each, ask:

- Is this still in use?
- Is it tagged correctly?
- Is the cost in line with expectations?

Resources that don't pass these checks get tagged and added to the next quarter's deletion list.

---

## The annual deep audit

Once a year, do a full sweep. This is more thorough than the quarterly audit:

- **Compare against the architecture docs.** Is every documented resource still in use? Are there resources in the account that aren't documented?
- **Review the cost explorer.** Where is the money going? Is each cost item justified?
- **Review the security audit logs.** Any unusual access patterns on old resources?
- **Update the architecture docs.** If the system has evolved, the docs should reflect that.

---

## Anti-patterns

### 1. "We'll clean it up later"

The most common anti-pattern. "Later" never comes. Tag the resource as `orphan-pending` immediately when it becomes orphaned. Do not wait.

### 2. "Let's just disable it"

A disabled Lambda function still costs money to store. A stopped EC2 instance still costs money for the EBS volume. "Disabling" is not "deleting." If you're not going to delete it, have a reason and a reactivation plan.

### 3. "It might be useful someday"

If you can't articulate a specific reactivation plan, it's not useful. Delete it. If you need it back, you can recreate it (and you'll probably recreate it differently anyway).

### 4. "Let's keep it for compliance"

Compliance requires you to keep data, not infrastructure. Take a snapshot, delete the live resource, store the snapshot in cold storage (Glacier or equivalent). This satisfies compliance at a fraction of the cost.

### 5. "I'll just rename it"

Renaming hides the orphan from the next audit. Don't rename. Tag it `orphan-pending` so it's visible.

---

## Self-hosting checklist

- [ ] Adopt a naming convention that includes environment, owner, purpose, and status
- [ ] Run the quarterly audit checklist
- [ ] Tag every new resource correctly at creation time
- [ ] Have a deletion process (tag, backup, wait 30 days, delete, verify)
- [ ] Run a monthly review of new resources
- [ ] Run an annual deep audit
- [ ] Have a cost-explorer dashboard showing cost per resource

---

## Next

- [`10-adrs.md`](10-adrs.md) — the architecture decision records, including "why did we use two pools?" and "why is the fingerprinter on-demand?"
