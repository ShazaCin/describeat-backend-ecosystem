# Security Policy

## Supported versions

The following versions of DescribeAT receive security updates:

| Version | Supported          |
|---------|--------------------|
| Latest (main branch) | ✅ Yes |
| Older versions | ❌ No |

This is a documentation project, not a long-running software release. Security updates are applied to the main branch. We do not maintain older versions.

---

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report them privately via one of these channels:

1. **Email:** [security contact — to be added before public launch]
2. **GitHub security advisories:** Use [GitHub's private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) feature (Security tab → Report a vulnerability).

When reporting, please include:

- A description of the vulnerability and its impact
- Steps to reproduce, including any proof-of-concept code
- The affected version(s) (e.g. main branch, specific commit)
- Your name/handle (if you'd like to be credited in the fix)

You should receive a response within 5 business days. If you don't, follow up via the same channel.

---

## What we will do

When you report a vulnerability:

1. **Acknowledge** your report within 5 business days
2. **Investigate** the issue and assess its severity
3. **Develop a fix** if the issue is in our code or documentation
4. **Release the fix** to the main branch
5. **Credit you** in the fix's commit message (if you want to be credited)
6. **Disclose** the issue publicly after the fix is released (typically 30-90 days after the report, depending on severity)

The timeline depends on the severity and the complexity of the fix.

---

## What we will NOT do

- We will not threaten legal action against you for reporting a vulnerability in good faith
- We will not require you to sign an NDA before reporting (unless your organisation requires one)
- We will not pay bounties for vulnerability reports (this project is open-source and unmaintained financially)
- We will not fix issues in third-party dependencies (file those with the upstream project)

---

## Security considerations for self-hosters

This documentation describes how to deploy DescribeAT. Self-hosters are responsible for their own security. The most common security pitfalls:

### 1. Forgetting the admin domain allowlist

The admin user pool must have a hard allowlist of email domains. Without it, anyone with a Google account can sign in as admin.

**Fix:** Configure the PreSignUp Lambda to reject emails from non-allowlisted domains. See [`examples/cognito-app-client.example.json.md`](examples/cognito-app-client.example.json.md) for the configuration.

### 2. Committing secrets to source control

The `.env` file, `amplify-meta.json`, and other configuration files may contain secrets. Never commit them.

**Fix:** Use Secrets Manager. Add `.env`, `.env.local`, and `amplify-meta.local.json` to `.gitignore`.

### 3. Exposing the data layer to the public internet

The data layer should only be accessible via the CDN, which handles authentication and authorization. Direct access bypasses your security controls.

**Fix:** Place the data layer in a private subnet. Only the CDN can reach it.

### 4. Using `statuses: [0, 200]` on CDN cache rules

Opaque responses (status 0) cached as 200 will serve corrupted content to listeners. See [`workflows/incident-response.md`](workflows/incident-response.md) for details.

**Fix:** Use `statuses: [200]` only. Validate this in your CDN config before deploying.

### 5. Not rotating credentials when admins leave

When an admin leaves the team, their access must be revoked immediately. See [`workflows/rotating-credentials.md`](workflows/rotating-credentials.md).

**Fix:** Have an off-boarding checklist. Disable the user in the auth provider within 1 hour of departure.

### 6. Not enabling MFA on the admin pool

Admins should have MFA required. Without it, a stolen password gives full admin access.

**Fix:** Set `MFAConfiguration: "ON"` on the admin user pool. See the example in [`examples/cognito-app-client.example.json.md`](examples/cognito-app-client.example.json.md).

---

## Security considerations for content contributors

If you contribute AD content to a DescribeAT deployment, you are responsible for the licensing and provenance of the content. The DescribeAT project does not verify or warrant the licensing of contributed content.

**Do not contribute:**

- Content you do not have the right to license
- Content that contains personal information of third parties without their consent
- Content that infringes on the intellectual property rights of others
- Content that is malicious, harmful, or misleading

---

## Cryptography

DescribeAT does not implement its own cryptography. It relies on:

- **TLS** for transport security (handled by the CDN and auth provider)
- **JWT signatures** for auth tokens (handled by the auth provider)
- **Pre-signed URLs** for storage access (handled by the storage service)

Self-hosters should not implement their own cryptography. Use the managed services.

---

## Reporting a security issue in a deployment

If you find a security issue in someone else's deployment of DescribeAT, report it to the deployment owner. Do not report it to the DescribeAT project — we don't operate the deployments.

---

## Disclosures

This section lists publicly disclosed security issues that have been fixed.

_No security disclosures yet. This section will be updated as issues are reported and fixed._

---

## Contact

For security issues: see the "Reporting a vulnerability" section above.

For non-security issues: open a public issue.
