# Cognito App Client configuration (example)

> The shape of the Cognito App Client configuration that the PWA and admin portal expect. The values are placeholders — your actual deployment will have different IDs.

---

## App pool client (for listeners)

```json
{
  "UserPoolId": "us-east-1_XXXXXXXXX",
  "ClientId": "xxxxxxxxxxxxxxxxxxxxxxxxxx",
  "ClientName": "describeat-app-web",
  "ClientSecret": "<REDACTED - use Secrets Manager>",
  "GenerateSecret": false,
  "RefreshTokenValidity": 30,
  "AccessTokenValidity": 60,
  "IdTokenValidity": 60,
  "TokenValidityUnits": {
    "AccessToken": "minutes",
    "IdToken": "minutes",
    "RefreshToken": "days"
  },
  "AllowedOAuthFlows": ["code"],
  "AllowedOAuthScopes": ["openid", "email", "profile"],
  "AllowedOAuthFlowsUserPoolClient": true,
  "CallbackURLs": [
    "https://app.example.com/auth/callback",
    "https://app.example.com"
  ],
  "LogoutURLs": [
    "https://app.example.com"
  ],
  "DefaultRedirectURI": "https://app.example.com/auth/callback",
  "SupportedIdentityProviders": ["Google"],
  "PreventUserExistenceErrors": "ENABLED",
  "EnableTokenRevocation": true,
  "EnablePropagateAdditionalUserContextData": false,
  "AuthSessionValidity": 3,
  "ReadAttributes": ["email", "name", "sub"],
  "WriteAttributes": ["email", "name"]
}
```

### What to note

- **`RefreshTokenValidity: 30`** — refresh tokens last 30 days. Users stay signed in for a month.
- **`AccessTokenValidity: 60`** — access tokens last 60 minutes. After 60 minutes, the app uses the refresh token to get a new one transparently.
- **`GenerateSecret: false`** — public clients (SPAs) cannot securely store a secret. Use PKCE instead.
- **`AllowedOAuthFlows: ["code"]`** — Authorization Code flow with PKCE. Do not use implicit flow (deprecated).
- **`CallbackURLs`** — must be registered. Include both `https://app.example.com` and `https://app.example.com/auth/callback` for flexibility.
- **`SupportedIdentityProviders: ["Google"]`** — only Google. Add more if needed (Apple, Facebook, etc.).

---

## Admin pool client (for admins)

```json
{
  "UserPoolId": "us-east-1_YYYYYYYYY",
  "ClientId": "yyyyyyyyyyyyyyyyyyyyyyyyyy",
  "ClientName": "describeat-admin-web",
  "ClientSecret": "<REDACTED - use Secrets Manager>",
  "GenerateSecret": true,
  "RefreshTokenValidity": 1,
  "AccessTokenValidity": 15,
  "IdTokenValidity": 15,
  "TokenValidityUnits": {
    "AccessToken": "minutes",
    "IdToken": "minutes",
    "RefreshToken": "days"
  },
  "AllowedOAuthFlows": ["code"],
  "AllowedOAuthScopes": ["openid", "email", "profile", "custom:role"],
  "AllowedOAuthFlowsUserPoolClient": true,
  "CallbackURLs": [
    "https://admin.example.com/auth/callback",
    "https://admin.example.com"
  ],
  "LogoutURLs": [
    "https://admin.example.com"
  ],
  "DefaultRedirectURI": "https://admin.example.com/auth/callback",
  "SupportedIdentityProviders": ["Google"],
  "PreventUserExistenceErrors": "ENABLED",
  "EnableTokenRevocation": true,
  "MFAConfiguration": "ON",
  "SoftwareTokenMFAConfiguration": {
    "Enabled": true
  },
  "ReadAttributes": ["email", "name", "sub", "custom:role"],
  "WriteAttributes": ["email", "name"]
}
```

### What's different from the app pool

- **`RefreshTokenValidity: 1`** — refresh tokens last 1 day. Admins re-auth daily.
- **`AccessTokenValidity: 15`** — access tokens last 15 minutes. Short sessions.
- **`GenerateSecret: true`** — the admin portal is a server-side app and can store a secret.
- **`MFAConfiguration: "ON"`** — MFA is required. `SoftwareTokenMFAConfiguration.Enabled: true` enables TOTP (authenticator apps).
- **`custom:role`** — the custom attribute that the data layer uses for role-based access.

---

## The PreSignUp Lambda (admin pool only)

The admin pool requires a Lambda trigger to enforce the email domain allowlist:

```javascript
// lambda/domain-allowlist.js
exports.handler = async (event) => {
  const email = event.request.userAttributes.email;
  const allowedDomains = (process.env.ALLOWED_ADMIN_DOMAINS || '').split(',');
  
  if (!email) {
    throw new Error('Email is required for admin sign-up.');
  }
  
  const domain = email.split('@')[1].toLowerCase();
  
  if (!allowedDomains.includes(domain)) {
    throw new Error(`Sign-up is not allowed for email domain: ${domain}`);
  }
  
  return event;
};
```

Configure this Lambda as a PreSignUp trigger on the admin user pool:

```bash
aws cognito-idp update-user-pool \
  --user-pool-id "us-east-1_YYYYYYYYY" \
  --lambda-config "PreSignUp=arn:aws:lambda:REGION:ACCOUNT:function:domain-allowlist"
```

The `ALLOWED_ADMIN_DOMAINS` environment variable is a comma-separated list:

```
ALLOWED_ADMIN_DOMAINS=your-org.com,partners.org
```

---

## Testing the configuration

### Test the app pool

1. Sign in with a personal Gmail account. Should succeed.
2. Sign in with a corporate email. Should also succeed (no allowlist).
3. Verify the tokens are valid for the configured durations.

### Test the admin pool

1. Sign in with an allowed-domain email. Should succeed.
2. Sign in with a non-allowed email. Should fail with "Sign-up is not allowed for email domain."
3. Verify MFA is required.
4. Verify the session lifetime is short (sign out, try to use a token from yesterday, should fail).
