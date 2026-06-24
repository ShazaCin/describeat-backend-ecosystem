# 06 — Notifications

> Push notifications from the admin portal to listener devices.

---

## The architecture

DescribeAT uses Firebase Cloud Messaging (FCM) as the cross-platform push provider. FCM handles both web (Chrome, Firefox, Edge) and iOS Safari push (with caveats — see iOS section below).

```
[Admin portal: "Send notification" form]
        |
        |  (1) Admin submits notification (title, body, recipients)
        v
[Admin portal writes UserNotification record to data layer]
        |
        |  (2) Admin portal invokes a Lambda with the notification ID
        v
[Lambda looks up FCM tokens for the recipient user(s)]
        |
        |  (3) Lambda calls FCM HTTP v1 API with the notification payload
        v
[FCM routes to the appropriate platform service]
        |
        |  (4a) For Android/Chrome/Firefox: FCM direct delivery
        |  (4b) For iOS Safari: FCM → APNs → device
        v
[Device displays the notification]
```

**The live path is direct Lambda → FCM.** The original production deployment has an alternative path (DynamoDB stream → SQS → Lambda → FCM), but that path is broken — the DynamoDB stream trigger was never wired up correctly. If you need queue-based notification delivery, build it fresh. Don't try to fix the existing broken path.

---

## Token registration

When a listener installs the PWA and grants notification permission, the app generates a device token and registers it with the backend.

### The flow

```
[User grants notification permission in the PWA]
        |
        |  (1) Service worker requests a token from FCM
        v
[FCM returns a device token]
        |
        |  (2) App calls POST /api/notifications/register-token
        |      with { userId, deviceToken, platform, userAgent }
        v
[Data layer writes a FCM Tokens row]
        |
        |  (3) Token is now available for future notification sends
```

**Authentication required:** Token registration requires a valid user JWT. Without auth, anyone could register a token for any user and receive their notifications.

**One user, many devices:** A user with two devices (phone + laptop) has two FCM Tokens rows. Notifications are sent to all of them.

### Token lifecycle

| Event | What happens |
|-------|--------------|
| User grants permission | New FCM Tokens row created |
| User revokes permission | FCM Tokens row deleted |
| Token expires (FCM rotates it) | New row created, old row marked invalid |
| Push fails with `NotRegistered` error | Row marked invalid, deleted on next cleanup |
| User uninstalls the app | Token invalid on next push attempt, cleaned up |

**The cleanup job:** A daily job that deletes FCM Tokens rows that haven't been successfully pushed to in 30+ days. This keeps the table from growing unboundedly.

---

## Sending a notification

### From the admin portal

```
1. Admin opens the admin portal
2. Admin clicks "Send Notification"
3. Admin fills in:
   - Title (headline)
   - Body (the message)
   - Recipients (specific users, or a group like "all_users")
   - Optional: deep link, image
4. Admin clicks "Send"
5. Admin portal:
   a. Validates the inputs
   b. Writes a UserNotification record to the data layer (status: pending)
   c. Invokes the notification Lambda with the notification ID
   d. Updates the notification record's status to "sending"
6. Lambda:
   a. Looks up FCM tokens for the recipients
   b. Sends a push to each token
   c. Records success/failure per token
   d. Updates the notification record's status (delivered, partial_failure, or failed)
```

### The Lambda code shape

```python
import json
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize once at cold start
cred = credentials.Certificate({...})  # from Secrets Manager
firebase_admin.initialize_app(cred)

def handler(event, context):
    notification_id = event['notificationId']
    notification = data_layer.get_notification(notification_id)
    tokens = data_layer.get_tokens_for_recipients(
        notification['recipientUserIds'] or notification['recipientGroup']
    )
    
    results = {'success': 0, 'failure': 0, 'invalid_tokens': []}
    
    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=notification['title'],
                    body=notification['body'],
                    image=notification.get('imageUrl'),
                ),
                data={'notificationId': notification_id, 'deepLink': notification.get('deepLink', '')},
                token=token['deviceToken'],
            )
            messaging.send(message)
            results['success'] += 1
        except messaging.UnregisteredError:
            results['invalid_tokens'].append(token['tokenId'])
            results['failure'] += 1
        except Exception as e:
            results['failure'] += 1
            log_error(e)
    
    data_layer.update_notification_status(notification_id, results)
    return results
```

This is illustrative. The actual implementation depends on your cloud provider, FCM SDK version, and data layer choice.

---

## iOS specifics

iOS push has several quirks that don't apply to Android or web.

### iOS 16.4+ required

iOS Safari push requires iOS 16.4 or later. Older versions silently fail. **Test on actual devices, not just simulators.**

### PWA must be installed to home screen

iOS Safari push does not work in browser tabs. The PWA must be **added to the home screen** first. This is an Apple platform limitation.

**The implication:** You need to tell users to add the PWA to their home screen in your onboarding flow. Browser-tab users will see "Notifications are not supported" and have no way to know they need to install the PWA first.

### The Firebase SDK in the service worker

iOS Safari requires the Firebase Messaging SDK to be loaded in the service worker context. If the SDK is loaded in the main thread only, push does not work on iOS.

**Fix:** The service worker must `importScripts()` the Firebase SDK. This is a one-time setup step that's easy to forget.

**Verification:** Test on an actual iOS device, installed to the home screen. There is no reliable way to test iOS push in a simulator.

### Cold-start timing

On iOS PWA, after the app is closed and reopened, the service worker may not be active. The first push received may be dropped if the SW isn't ready.

**Fix:** Call `navigator.serviceWorker.ready` before requesting a token. The `ready` promise resolves when the SW is fully installed and active.

---

## Accessibility — critical for DescribeAT

The primary user of DescribeAT is blind or visually impaired. The notification UI must work with VoiceOver, TalkBack, and NVDA.

### The hidden spinner trap

A common bug: the notification settings UI shows a button, the user taps it, a spinner appears, the spinner disappears, and nothing else happens. To a sighted user, the user might assume the action succeeded. To a VoiceOver user, the button tap produced no audible feedback at all — the spinner was silent.

**Fix:** Every async action must leave a visible, announced status. The pattern is:

```html
<button id="enable-notifications">Enable notifications</button>

<div id="status" role="status" aria-live="polite"></div>

<script>
button.addEventListener('click', async () => {
  status.textContent = 'Requesting permission...';
  try {
    await Notification.requestPermission();
    status.textContent = 'Notifications enabled.';
  } catch (e) {
    status.textContent = 'Failed to enable notifications: ' + e.message;
  }
});
</script>
```

The `role="status"` and `aria-live="polite"` make the screen reader announce the status change. Without these attributes, the text changes are silent.

### The error trap

Same pattern for errors. Use `role="alert"` (which is assertive, interrupts the current announcement) for errors that need immediate attention.

```html
<div id="error" role="alert"></div>
```

### The icon-only button trap

iOS Safari drops `aria-label` from icon-only `<button>` elements in standalone (home screen) mode. This is a long-standing WebKit bug. The fix:

```html
<button aria-label="Enable notifications">
  <span class="sr-only">Enable notifications</span>
  <svg>...</svg>
</button>
```

The `<span class="sr-only">` is a visually-hidden text label that VoiceOver will announce even when `aria-label` is ignored.

---

## Common mistakes when deploying

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Firebase credentials in source code | Compromised on first push to git | Use Secrets Manager |
| Token registration endpoint requires no auth | Anyone can register tokens for any user | Require JWT in the Authorization header |
| Token cleanup job not running | FCM Tokens table grows unboundedly | Run a daily cleanup job |
| iOS push not working | iOS users never get notifications | Check iOS version, PWA installed to home screen, Firebase SDK in SW |
| Notification permission requested on first app open | High refusal rate | Request permission in context, after the user has seen value |
| Notification body too long | Truncated on iOS | Keep body under 100 characters |
| Notification title is the same for all notifications | Users ignore them | Vary the title; describe the content |
| Deep link goes to a 404 | User taps notification, sees error | Test deep links; ensure the routes exist |
| Notification sent to deleted/invalid token | Push fails | Validate tokens before sending; clean up invalid ones |

---

## What to monitor

- **Token registration rate.** Should be roughly equal to the new user sign-up rate. A sudden drop = onboarding flow is broken.
- **Notification delivery rate (per send).** Should be >95% for valid tokens. A drop = FCM issues or token staleness.
- **Notification open rate.** How many users tap the notification. Low = the content isn't useful or the timing is off.
- **Token invalidation rate.** How many tokens become invalid per day. Spikes = user uninstalls or FCM rotation.

---

## Privacy and consent

### What you can do without explicit consent

In most jurisdictions, you can send notifications to a user who has:
- Signed up for an account
- Granted notification permission in their browser/OS
- Not opted out of notifications

You **cannot** send notifications to a user who has not granted permission. Period.

### What you should ask before sending

For sensitive categories of notifications, ask before sending. Examples:
- **Marketing notifications:** Almost always requires explicit opt-in.
- **System notifications** (app updates, security alerts): Usually OK without opt-in, but provide an opt-out.
- **Content recommendations:** Borderline. Some jurisdictions require opt-in.

### The unsubscribe flow

Every notification should have an unsubscribe option. The simplest pattern: a "Notification settings" page in the user's profile, with checkboxes for each notification type.

**Make the unsubscribe one-tap.** Don't require the user to log in to a separate system, fill out a form, or send an email. One tap, instant unsubscribe.

---

## Self-hosting checklist

- [ ] FCM project is created and credentials are in Secrets Manager
- [ ] Token registration endpoint requires auth
- [ ] FCM Tokens table has the correct schema
- [ ] Token cleanup job is scheduled (daily)
- [ ] Notification Lambda is wired up to the admin portal
- [ ] iOS push is tested on a real device with iOS 16.4+
- [ ] Android push is tested on a real device
- [ ] Web push is tested on Chrome, Firefox, Edge
- [ ] Notification UI uses `role="status"` and `role="alert"` for async feedback
- [ ] Icon-only buttons have `<span class="sr-only">` labels
- [ ] Notification body is under 100 characters
- [ ] Unsubscribe flow is one-tap
- [ ] You have a runbook for "FCM is returning errors"

---

## Next

- [`07-deploy-your-own.md`](07-deploy-your-own.md) — step-by-step deployment
- [`workflows/incident-response.md`](../workflows/incident-response.md) — when things go wrong
