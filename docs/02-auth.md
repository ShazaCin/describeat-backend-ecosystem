# 02 — Authentication

> The two-pool model that handles app listeners and admin users.

---

## The two pools in one paragraph

DescribeAT has two distinct user populations, and they have fundamentally different authorization rules. Listeners (blind/VI users of the app) need frictionless sign-in via Google. Admins (content managers, support staff) need to be hard-locked to specific email domains, optionally with MFA, and their access revoked the moment they leave the team.

These are different enough that a single pool with role-based access becomes a maintenance burden at the first 100 users. The system uses two pools, and they have separate OAuth client configurations, separate allowed email domains, separate session lifetimes, and separate MFA requirements.

**This is not negotiable. Do not merge them into one pool with role-based access.** See §"The merger trap" below for why.

---

## Pool 1: The App pool (listeners)

| Setting | Value | Rationale |
|---------|-------|-----------|
| Sign-in method | Google OAuth (hosted UI) | Frictionless for users on any device |
| Allowed email domains | Any (no allowlist) | Listeners may use any email |
| Session lifetime (access token) | 1 hour | Re-auth once an hour |
| Session lifetime (refresh token) | 30 days | Stay signed in for a month |
| MFA | Optional | Listeners on shared devices may not have a phone for MFA |
| User attributes exposed to app | email, name, sub | Display name + user ID |
| Custom attributes | None | Listeners don't need internal flags |

**Domain allowlist:** The app pool does NOT have a domain allowlist. Listeners can sign in with any Google account. If you self-host and want to restrict to a specific domain (corporate deployment, school rollout), add the allowlist post-creation. Don't do it for a public deployment — it blocks the whole point.

---

## Pool 2: The Admin pool (content managers)

| Setting | Value | Rationale |
|---------|-------|-----------|
| Sign-in method | Google OAuth (hosted UI) | Same UX as the app pool |
| **Allowed email domains** | **Hard-coded allowlist** (e.g. `your-org.com`, `partners.org`) | Only your team can be admins |
| Session lifetime (access token) | 15 minutes | Short — admins should re-auth often |
| Session lifetime (refresh token) | 24 hours | Daily re-auth required |
| MFA | **Required** (TOTP) | Admin access is high-value |
| User attributes exposed to app | email, name, sub, custom:role | Role-based UI in the admin portal |
| Custom attributes | `role` (one of: `superadmin`, `editor`, `support`, `viewer`) | Different permissions per role |

**Domain allowlist is the load-bearing security control.** The admin pool MUST have a hard allowlist of email domains. If you deploy DescribeAT and forget to set this, anyone with a Google account can sign in as admin. There is no way to recover from this after it happens — you have to delete the pool and start over.

**How to set the allowlist (per managed-auth-provider example):**
- AWS Cognito: PreSignUp Lambda trigger that rejects sign-ups with disallowed email domains
- Auth0: "Connections → Database → Rules"
- Keycloak: "Authentication → Flows → Registration → Domain Checker"

The mechanism varies. The behavior is non-negotiable.

---

## The merger trap (read this before refactoring)

A future contributor will look at the two pools and think: "Why two? I'll merge them into one with a `role` attribute. Simpler." **Resist this.** Here is why:

| Concern | Two pools | One pool + role |
|---------|-----------|-----------------|
| **Domain allowlist on admins** | Hard-coded in the admin pool config; not exposed to app users | Has to be re-implemented as a runtime check on every admin action. Easy to forget. Easy to bypass. |
| **Session lifetime** | App pool: 1h access, 30d refresh. Admin pool: 15min access, 24h refresh. Different policies per population. | One policy for everyone. Listeners re-auth every 15 minutes (annoying) OR admins get 30-day sessions (insecure). |
| **MFA** | Admin: required. App: optional. | One setting for everyone. If you require MFA for everyone, listeners on shared devices can't sign in. If you make it optional, an admin can opt out. |
| **OAuth client config** | Different redirect URIs, different scopes, different consent screens. | One config, harder to audit which client can do what. |
| **Incident response** | If admin pool is compromised, you delete the pool and recreate. App users unaffected. | If the role check is bypassed, every user is potentially an admin. Blast radius is the whole user base. |

The two pools is the right shape. The "complexity" of two pools is dwarfed by the operational pain of a single pool with roles.

**If you absolutely must consolidate** (you don't, but if): use a *third* auth provider (Auth0, Clerk, WorkOS) that supports organizations/roles natively, and use two separate organizations within that provider. The two-organization pattern is the same as the two-pool pattern, just expressed in different vocabulary.

---

## OAuth flow: what the listener sees

```
[Listener's phone]
        |
        |  (1) User taps "Sign in" in the PWA
        v
[App calls signInWithRedirect() — opens the hosted UI in a browser window]
        |
        |  (2) Hosted UI shows Google's "Choose an account" page
        v
[Listener picks their Google account]
        |
        |  (3) Google returns the user's profile to the hosted UI
        v
[Hosted UI issues an authorization code]
        |
        |  (4) Hosted UI redirects to the app's registered redirect URL
        |      with ?code=...&state=... in the query string
        v
[App receives the redirect, exchanges the code for tokens]
        |
        |  (5) App receives: id_token, access_token, refresh_token
        v
[App stores tokens, calls userInfo endpoint to get profile, renders the home screen]
```

**Latency budget:** The whole flow should complete in under 5 seconds on a good network. Most of the time is Google's "Choose an account" page.

**Pitfall — stale service worker intercepts the redirect:**

When the PWA's service worker (SW) intercepts the OAuth redirect back to the app, it serves the **cached `index.html` + old JS bundle** from disk. The new bundle may have a different schema, different API endpoints, different auth code. The result is a "signed in but content area is blank" symptom that's almost impossible to debug from the user side.

**Fix:** SW should **never** intercept navigations to the auth callback URL. Whitelist the auth callback path. This is a known iOS PWA footgun; see [`workflows/incident-response.md`](../workflows/incident-response.md) for the diagnostic recipe.

**Pitfall — iOS VoiceOver on hosted UI:**

iOS opens the hosted UI in an `SFSafariViewController` (in-app Safari). This page comes from Google's sign-in flow, not your code. VoiceOver announces Safari toolbar items (Back, Share, Reader View, etc.) — confusing for screen-reader users. **Workaround:** Tell iOS users to sign in once in regular Safari first, then open the PWA. The session may transfer.

**Better fix:** Implement email/password sign-in directly in the PWA (no hosted UI). This is more work but gives you full control over the accessibility of the sign-in flow.

---

## JWT structure (for backend-to-backend calls)

When the app or admin portal calls the data layer, it sends a JWT in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

The JWT contains:
- `sub` — the user's unique ID (Cognito sub, a UUID)
- `email` — the user's email
- `cognito:groups` — the groups the user belongs to (used for role-based access in the data layer)
- `exp` — expiration timestamp
- `iss` — the auth provider's URL

**Never trust the JWT for authorization decisions without verifying the signature.** Every backend service that accepts JWTs must verify the signature against the auth provider's public key. The data layer does this for you; custom Lambda functions must do it explicitly.

**Never put sensitive data in the JWT.** It's a bearer token — anyone who has it has the user's access. If you need to pass sensitive data, use the user info endpoint with the access token, not the JWT itself.

---

## Token refresh

Access tokens expire (1h for app pool, 15min for admin pool). When the access token expires, the client uses the refresh token to get a new access token. This happens transparently in the SDK.

**If the refresh token expires** (30 days for app, 24h for admin), the user has to sign in again. There's no "remember me" checkbox that survives this — the refresh token IS the remember-me.

**For admin users**, the daily re-auth is intentional. An admin's laptop left logged in overnight is a security incident; the daily re-auth forces the issue.

---

## The 2026 OAuth scope incident (lesson learned)

In June 2026, a code change in the admin pool's OAuth client configuration inadvertently removed a custom scope from the admin's allowed scopes. The result: admin users could not sign in, because their OAuth token did not include the scope the data layer required to authorize admin actions. The fix was restoring the scope to the admin pool's app client settings.

**Lesson:** When you change OAuth client configuration, verify the change in BOTH pools if it affects shared scopes. The two pools are different objects on the same auth provider — a change to one does not propagate to the other.

**Diagnostic recipe for "I can't sign in" reports:**
1. Check the browser console for OAuth errors. The error message is usually specific.
2. Check the data layer's auth logs. A 401 with a specific scope name is the giveaway.
3. Compare the OAuth client config between the two pools. If they should be the same and aren't, that's the bug.
4. Restore the missing scope. Test in both pools.

---

## Common mistakes when deploying

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Forgot to set the admin domain allowlist | Anyone with Google can sign in as admin | Add the allowlist, then audit admin users and remove any that shouldn't be there |
| Set the app pool's domain allowlist by accident | Listeners can't sign in | Remove the allowlist from the app pool |
| Used the same OAuth client for both pools | Cross-pool token confusion, hard to audit | Create separate OAuth clients (one per pool) |
| Set admin session lifetime to 30 days (the app pool default) | Admin sessions are too long, security risk | Set admin session to 15min access / 24h refresh |
| Made MFA optional on the admin pool | Admin can skip MFA, security risk | Make MFA required (TOTP) for the admin pool |
| Hard-coded an email address in the admin allowlist | Only one person can be admin | Use email *domain* patterns, not specific addresses |
| Forgot to set the OAuth redirect URIs for both pools | "Redirect URI mismatch" errors | Register the redirect URI on both pools separately |

---

## What to monitor

- **Failed sign-in rate** (per pool). A sudden spike means either a bug, a credential stuffing attack, or an OAuth config change.
- **Admin sign-ins from new locations**. A new IP signing in as admin is a security event.
- **Token refresh failures**. If many users' refresh tokens are failing, the auth provider may be having an issue.
- **MFA bypass attempts**. If an admin's MFA is being skipped, your auth config is wrong.

---

## Self-hosting checklist

When you deploy your own DescribeAT backend, before going live:

- [ ] App pool: domain allowlist is **empty** (any domain allowed)
- [ ] Admin pool: domain allowlist contains **only your team's domain(s)**
- [ ] App pool: session lifetime 1h access / 30d refresh
- [ ] Admin pool: session lifetime 15min access / 24h refresh
- [ ] Admin pool: MFA required (TOTP)
- [ ] Two separate OAuth clients (one per pool)
- [ ] OAuth redirect URIs registered on both pools
- [ ] Custom `role` attribute exists on the admin pool
- [ ] Admin user records exist with the correct `role` values
- [ ] Audit log table exists and is being written to
- [ ] You have a runbook for revoking admin access when a team member leaves

If you can tick every box, your auth setup is correct. If you can't, fix it before going live.

---

## Next

- [`03-data-model.md`](03-data-model.md) — the entities the auth pool protects
- [`07-deploy-your-own.md`](07-deploy-your-own.md) — deploying this from scratch
- [`workflows/rotating-credentials.md`](../workflows/rotating-credentials.md) — what to do when an admin leaves
