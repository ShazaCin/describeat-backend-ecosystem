# Runbook: Rotating credentials

> How to rotate credentials when an admin leaves the team, when a secret is suspected to be compromised, or on a regular schedule.

---

## When to rotate

### Triggered rotations

- **Admin leaves the team** — their access must be revoked immediately
- **Suspected compromise** — any time you suspect a secret has leaked
- **Third-party breach** — if a third party you integrate with (auth provider, FCM, etc.) reports a breach
- **Audit finding** — if a security audit identifies a credential that should be rotated
- **Quarterly schedule** — even without an incident, rotate secrets quarterly

### What to rotate

- **Admin user records** — remove from the user pool, archive their actions
- **OAuth client secrets** — rotate the secret, update the data layer
- **API keys** — for any third-party service with API keys
- **Service account credentials** — for FCM, AWS, etc.
- **JWT signing keys** — for any custom auth implementation
- **Database passwords** — for the data layer's database
- **Pre-signed URL signing keys** — for the storage service

---

## The rotation process

### Step 1: Identify what to rotate

List every credential that needs to change. For each, document:

- What it is
- Where it's stored
- Who has access to it
- What depends on it (which services use it)

### Step 2: Generate the new credential

For each credential:

1. Generate a new value (new API key, new OAuth secret, new database password)
2. Store it in Secrets Manager (or equivalent)
3. Do NOT distribute it yet

### Step 3: Update dependent services

For each service that uses the credential:

1. Update the service to read the new value from Secrets Manager
2. Restart the service
3. Verify the service is working with the new credential

Do this in a test environment first, then production.

### Step 4: Switch over

Once all services are using the new credential:

1. Disable the old credential (revoke the old API key, etc.)
2. Verify the services still work (they should — they're using the new credential)
3. If anything breaks, re-enable the old credential and investigate

### Step 5: Document the rotation

In the audit log, record:

- What was rotated
- When it was rotated
- Who performed the rotation
- Why it was rotated (incident, schedule, etc.)
- The new credential's identifier (NOT the value)

### Step 6: Communicate if needed

If the rotation affects admins (e.g. they need to re-authenticate), notify them in advance. Surprise rotations cause confusion and incident reports.

---

## Specific procedures

### Rotating an admin's access when they leave the team

**Priority:** Critical. Do this within 1 hour of the team member's departure.

```bash
# Disable the user in Cognito
aws cognito-idp admin-disable-user \
  --user-pool-id "us-east-1_YYYYYYYYY" \
  --username "admin@example.com"

# Force sign-out (invalidate all sessions)
aws cognito-idp admin-user-global-sign-out \
  --user-pool-id "us-east-1_YYYYYYYYY" \
  --username "admin@example.com"

# Remove the user from any groups
aws cognito-idp admin-remove-user-from-group \
  --user-pool-id "us-east-1_YYYYYYYYY" \
  --username "admin@example.com" \
  --group-name "editors"

# (Optional) Delete the user entirely
aws cognito-idp admin-delete-user \
  --user-pool-id "us-east-1_YYYYYYYYY" \
  --username "admin@example.com"
```

**Don't delete the user immediately.** Disable first, then delete after 30 days. This gives you a recovery window if the departure was a mistake or if you need to reference the user's audit log entries.

**Audit log review:** Review the user's actions over the past 30 days. Look for:

- Unusual access patterns
- Data exports
- User deletions
- Configuration changes

If you find anything suspicious, escalate to security.

### Rotating an OAuth client secret

```bash
# Generate a new secret (this also invalidates the old one)
aws cognito-idp update-user-pool-client \
  --user-pool-id "us-east-1_YYYYYYYYY" \
  --client-id "yyyyyyyyyyyyyyyyyyyyyyyyyy" \
  --generate-secret

# Get the new secret
aws cognito-idp describe-user-pool-client \
  --user-pool-id "us-east-1_YYYYYYYYY" \
  --client-id "yyyyyyyyyyyyyyyyyyyyyyyyyy"
```

Then:

1. Update the data layer to use the new secret
2. Update the admin portal to use the new secret
3. Test the admin portal sign-in flow
4. Delete the old secret from Secrets Manager after 30 days

### Rotating the FCM service account key

1. Generate a new service account key in the Firebase console
2. Store it in Secrets Manager
3. Update the notification Lambda to read the new key
4. Restart the Lambda
5. Send a test notification to verify
6. Delete the old key from Firebase

### Rotating the database password

1. Generate a new database password
2. Update the password in the database
3. Update the password in Secrets Manager
4. Update the data layer to read the new password
5. Restart the data layer
6. Test the data layer
7. Delete the old password from Secrets Manager after 30 days

---

## What NOT to do

### Don't rotate too often

Rotating secrets has a cost (downtime risk, coordination effort). Quarterly is a good balance. Don't rotate daily or weekly unless you have a specific reason.

### Don't rotate without testing

Always test the rotation in a non-production environment first. A failed rotation in production is a major incident.

### Don't communicate the new value

Never share the new credential value via email, Slack, or any other unencrypted channel. Use Secrets Manager or a similar secure distribution mechanism.

### Don't forget the audit log

Every rotation should be recorded in the audit log. The audit log is your evidence that rotations are happening on schedule.

### Don't leave old credentials around

After 30 days, delete the old credential from all places (Secrets Manager, environment variables, config files). Old credentials that are no longer in use are a security risk.

---

## The quarterly rotation checklist

For each quarter, review and rotate:

- [ ] OAuth client secrets (app pool)
- [ ] OAuth client secrets (admin pool)
- [ ] FCM service account key
- [ ] Database password
- [ ] Any third-party API keys
- [ ] Any IAM access keys for service accounts
- [ ] Any signing keys for JWTs

For each:

- [ ] Generated the new value
- [ ] Stored in Secrets Manager
- [ ] Updated dependent services
- [ ] Tested the change
- [ ] Disabled the old value
- [ ] Recorded in the audit log
- [ ] Communicated to stakeholders (if applicable)

---

## The off-boarding checklist (admin leaving)

- [ ] Disable the user in Cognito (within 1 hour)
- [ ] Force sign-out (invalidate all sessions)
- [ ] Remove from all groups
- [ ] Review audit log for the last 30 days
- [ ] Rotate any credentials the user had access to
- [ ] Notify the team of the change
- [ ] After 30 days: delete the user record
