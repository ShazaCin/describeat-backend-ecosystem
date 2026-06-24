# Runbook: Incident response

> What to do when something goes wrong. The most common incidents, the diagnostic recipes, and the fixes.

---

## How to use this runbook

When an incident happens:

1. **Don't panic.** The system is designed to fail closed. If something is broken, it's not serving data; it's not silently corrupting data.
2. **Identify the symptom.** What is the user seeing? What is the alert saying?
3. **Find the matching section below.** Each section has: symptom, root cause, diagnostic recipe, fix.
4. **Follow the recipe in order.** Don't skip steps.
5. **Document the incident.** Use the template at the end of this runbook.

---

## Common incidents

### Incident 1: "Sync button does nothing"

**Symptom:** Listener taps "Sync" in the app, the spinner appears then disappears, no audio plays. VoiceOver users say "nothing happened."

**Likely root causes (in order of probability):**

1. **Service worker cache poisoning** — the app is running an old version that can't talk to the current API. Most common after a deploy.
2. **Auth failure** — the user's session is invalid, the API returns 401, the app can't fetch the title.
3. **T2S engine down** — the fingerprinting engine is not responding.
4. **Network failure** — the listener has no internet.
5. **iOS-specific** — the PWA is not added to the home screen, or the iOS version is < 16.4.

**Diagnostic recipe:**

```
1. Check the service worker status in the user's browser
   - Chrome DevTools → Application → Service Workers
   - If the SW version is old, the user needs to clear site data
2. Check the network requests
   - Chrome DevTools → Network
   - Look for failed requests to /t2s/sync or /api/*
3. Check the T2S engine health
   - curl https://t2s.example.com/health
   - Should return 200 with status: ok
4. Check the data layer health
   - curl https://api.example.com/health
   - Should return 200
5. Check the user's auth state
   - Have the user sign out and sign back in
   - If sync works after re-auth, it was an auth issue
```

**Fix:**

- If SW cache poisoning: have the user clear site data (Settings → Safari → Advanced → Website Data → Remove All on iOS; DevTools → Application → Clear storage on Chrome).
- If auth failure: re-authenticate. Check the auth provider's logs for errors.
- If T2S engine down: restart the matcher service. Check the engine's logs for the root cause.
- If network failure: not a server-side issue. The user needs to check their connection.
- If iOS-specific: guide the user to add the PWA to the home screen and verify iOS version.

---

### Incident 2: "Audio plays but it's wrong content"

**Symptom:** Listener syncs to a TV show, gets a match, plays the AD track, but the narration doesn't match what's on screen.

**Likely root causes:**

1. **Confidence threshold too low** — the engine is matching with low confidence, returning wrong matches.
2. **Fingerprint database corruption** — the hashes for one title have been mixed with another.
3. **Schema drift** — the titleId in the data layer doesn't match the titleId in the fingerprint database.
4. **User has multiple shows playing** — the recording is ambiguous.

**Diagnostic recipe:**

```
1. Check the T2S engine's response for the failed sync
   - The input_confidence should be > 0.85 for a confident match
   - If it's close to 0.85, the match is borderline
2. Check the closest_matches[] array
   - If the correct title is in the closest_matches but with slightly lower confidence,
     the threshold may be too low
3. Check the title's fingerprintingProgress
   - If it's < 100, the title is not fully fingerprinted
4. Check the hash database integrity
   - Run a consistency check: for each title, the number of hashes should match
     the expected count based on the audio length
```

**Fix:**

- If confidence threshold too low: raise the threshold to 0.85 (or your tuned value). Restart the matcher.
- If fingerprint database corruption: re-fingerprint the affected titles. See [adding-a-new-title.md](adding-a-new-title.md) for the procedure.
- If schema drift: reconcile the titleIds. Update either the data layer or the hash database to match.
- If user has multiple shows playing: this is a user issue, not a server issue. The system is working as designed.

---

### Incident 3: "CDN serving corrupted audio"

**Symptom:** Listeners report that some titles play audio, others don't. The audio that fails to play gets stuck at 0% or stalls mid-track.

**Likely root cause:** The CDN cached an opaque response (status 0, no real body) and is serving it as a 200.

**Diagnostic recipe:**

```
1. Check the CDN's cache for the affected URL
   - CloudFront: check the cache behavior for /media/ad-tracks/*
   - Cloudflare: check the cache rules for the media path
2. Look for the status code configuration
   - The cache should be set to: statuses: [200]
   - If it's set to: statuses: [0, 200], this is the bug
3. Test the URL directly
   - curl -I https://media.example.com/ad-tracks/{trackId}.mp3
   - Should return 200 with Content-Length > 0
   - If it returns 200 with Content-Length: 0, the cache is poisoned
```

**Fix:**

1. Update the cache rule to `statuses: [200]` only
2. Purge the affected URLs from the CDN
3. Verify the URLs return real content
4. Have the affected users clear their browser cache (the old cache may persist for up to 30 days)

**Prevention:** Always set `statuses: [200]` on cache rules. Never `[0, 200]`. Add this to your CDN config validation.

---

### Incident 4: "Push notifications not being delivered"

**Symptom:** Admins send notifications, but listeners report they don't receive them.

**Likely root causes:**

1. **FCM credentials invalid** — the service account key has been revoked or expired.
2. **Token cleanup too aggressive** — valid tokens are being deleted.
3. **iOS push not configured correctly** — iOS requires the PWA to be added to the home screen.
4. **User opted out** — the user disabled notifications in their device settings.

**Diagnostic recipe:**

```
1. Check the notification Lambda logs
   - Look for "UnregisteredError" or "InvalidArgument"
   - If you see many UnregisteredErrors, the token cleanup is too aggressive
2. Check the FCM service account
   - Verify the credentials are still valid
   - Test with a direct FCM call
3. Check the deliveryStatus of recent notifications
   - If deliveryStatus is "partial_failure", some tokens are invalid
4. Test on a known-good device
   - Send a test notification to your own device
   - If it works, the issue is specific to the affected users
```

**Fix:**

- If FCM credentials invalid: rotate the service account key. See [rotating-credentials.md](rotating-credentials.md).
- If token cleanup too aggressive: extend the cleanup window from 30 days to 90 days. Re-add any tokens that were incorrectly deleted.
- If iOS push misconfigured: verify the PWA is on the home screen, iOS 16.4+, Firebase SDK is in the service worker.
- If user opted out: not a server-side issue. The user needs to enable notifications in their device settings.

---

### Incident 5: "Data layer returning 500s"

**Symptom:** The PWA shows error messages; the admin portal is broken; GraphQL queries fail.

**Likely root causes:**

1. **Database connection exhausted** — too many concurrent connections.
2. **AppSync throttling** — the request rate exceeds the limit.
3. **Schema deployment mismatch** — the schema was updated but the resolvers weren't, or vice versa.
4. **Auth provider down** — Cognito (or equivalent) is not responding, every request fails auth.

**Diagnostic recipe:**

```
1. Check the data layer's health
   - curl https://api.example.com/health
   - Should return 200
2. Check the database connection pool
   - For Hasura + Postgres: SELECT count(*) FROM pg_stat_activity;
   - For AppSync + DynamoDB: check CloudWatch metrics for throttling
3. Check the auth provider's health
   - Try a direct call to the auth provider
   - If it's down, every authenticated request will fail
4. Check the data layer's logs
   - Look for the specific error message
   - 401 = auth issue, 403 = authorization issue, 500 = server error
```

**Fix:**

- If database connection exhausted: increase the connection pool size. If you can't, scale the data layer horizontally.
- If AppSync throttling: request a limit increase from AWS, or reduce the request rate.
- If schema deployment mismatch: redeploy the schema and resolvers together. Verify the versions match.
- If auth provider down: wait for the auth provider to recover, or switch to a backup if you have one.

---

### Incident 6: "Fingerprinting pipeline not running"

**Symptom:** New AD tracks are uploaded but `fingerprintingProgress` stays at 0.

**Likely root cause:** The trigger is not wired up, or the fingerprinter is not running.

**Diagnostic recipe:**

```
1. Check the trigger
   - For S3 events: check the S3 event notification configuration
   - For scheduled tasks: check the schedule
2. Check the fingerprinter service
   - For Fargate: check the desired count, check the logs
   - For Lambda: check the function logs
3. Try to trigger manually
   - Manually invoke the trigger with the input parameters
   - If it works, the trigger is broken
   - If it doesn't work, the fingerprinter is broken
```

**Fix:**

- If trigger broken: reconfigure the trigger. Test it.
- If fingerprinter broken: check the logs for the root cause. Restart the service. Verify the hash database is writable.

---

## The post-incident report

After every incident, write a post-incident report. The template:

```markdown
# Incident report: {title}

**Date:** YYYY-MM-DD
**Duration:** HH:MM (start to resolution)
**Severity:** Critical | High | Medium | Low
**On-call:** {name}

## Summary
One paragraph: what happened, what was affected, what the user impact was.

## Timeline
- HH:MM — First alert / user report
- HH:MM — On-call paged
- HH:MM — Root cause identified
- HH:MM — Fix applied
- HH:MM — Incident resolved

## Root cause
What actually caused the incident. Be specific. Don't say "human error" or "system bug." Say "the S3 event notification was not configured for the new bucket" or "the confidence threshold was 0.5 due to a config error in commit abc123."

## Impact
- Number of users affected
- Duration of impact
- Data loss (if any)
- Revenue impact (if any)

## Resolution
What fixed the incident.

## What we learned
What we now know that we didn't know before. What would have prevented this.

## Action items
- [ ] {action 1} — owner, due date
- [ ] {action 2} — owner, due date
- [ ] Add a test for this scenario
- [ ] Update the runbook with the diagnostic recipe
- [ ] Update monitoring to catch this earlier
```

---

## Prevention

The best incident is the one that doesn't happen. For each incident:

1. **Add a test** that would have caught it. The test should fail in CI if the bug regresses.
2. **Add monitoring** that would have alerted earlier. The alert should fire before users notice.
3. **Update the runbook** with the diagnostic recipe. Future on-calls will find it.
4. **Add a guardrail** that prevents the bug from being introduced again. Examples:
   - A config validation step that rejects `statuses: [0, 200]`
   - A schema consistency check that fails CI if the schema doesn't match the resolvers
   - A pre-deploy hook that verifies the trigger configuration

---

## The on-call rotation

If you have a team, set up a rotation. The on-call:

- Is available 24/7 for the duration of their rotation (typically 1 week)
- Has access to all the runbooks, dashboards, and credentials
- Has authority to make changes without approval (within the bounds of the runbooks)
- Hands off cleanly at the end of their rotation

If you're a one-person team, you're always on call. The runbook is your fallback when you're not available.

---

## When to escalate

Escalate to security immediately if:

- You suspect unauthorized access to your account
- You see unusual activity in the audit log
- You receive a report of a data breach
- A third party (auth provider, FCM, etc.) reports they were breached

Escalate to a cloud provider if:

- The issue is in their service (e.g. Cognito is having an outage)
- You've exhausted your runbook steps
- You need a limit increase

Escalate to the community if:

- You've identified a bug in the open-source code
- You have a question that the docs don't answer
- You have a deployment recipe that others would benefit from

---

## Related

- [adding-a-new-title.md](adding-a-new-title.md) — adding content
- [rotating-credentials.md](rotating-credentials.md) — credential lifecycle
- [09-orphaned-resources.md](../docs/09-orphaned-resources.md) — keeping the account tidy
