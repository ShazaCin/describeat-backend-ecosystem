# Sample data files

> Anonymised sample data for each entity. Use these to seed your local development environment, validate your data layer's resolvers, and onboard new contributors.

---

## What's in this directory

| File | Source entity | Items | Notes |
|------|---------------|-------|-------|
| `titles.sample.json` | Title | 3 | UUIDs are real-format; titles, writers, narrators redacted |
| `ad-tracks.sample.json` | AD Track | 3 | Track URLs are illustrative (do not call them — they don't exist); narrator names truncated |
| `user-notifications.sample.json` | User Notification | 3 | Test messages from a sample deployment |
| `user-feedback.sample.json` | User Feedback | 3 | Sample bug reports |
| `categories.sample.json` | Categories | 3 | Sample category data |

---

## What was redacted

- **Real titles, writers, narrators, actors** in `titles.sample.json` — these are the actual content metadata that was curated for the original production deployment. Replaced with `<redacted>`.
- **User emails** in `user-feedback.sample.json` — replaced with `sample-{n}@example.com`. The userIds (UUIDs) are kept because they're needed for FCM token correlation.
- **Specific feedback message debug info** — kept the structure (e.g. `"issues": ["listen"]`) but redacted the long debug dumps.
- **Track URLs** in `ad-tracks.sample.json` — replaced with `https://media.example.com/ad-tracks/{trackId}.mp3`. The original URLs referenced a CDN that no longer exists.

---

## What was NOT redacted

- **UUIDs** — these are opaque identifiers, safe to publish.
- **Schema field names** — they're public via GraphQL introspection already.
- **Schema field types** — same reason.
- **Enum values** — these are public via the schema.

---

## Schema vs data drift — important warning

Some fields in the sample data may be **NOT in the GraphQL schema**. For example:

- `score`, `rated`, `runtimeMinutes`, `wheretowatch` appear in `titles.sample.json` but may not be in the `Title` GraphQL type in your deployment
- They were either added by an older schema version, computed at resolver time, or stored but not returned via the API

This means a client querying `query { getTitle(id: ...) { score } }` might get a GraphQL error. The data is in storage but not exposed.

**For deployers**: either update the schema to expose these fields (preferred) or treat them as internal-only and don't try to query them via the API.

---

## How to use these samples

### 1. Seed your local development environment

Import these into your local data layer after deploying. The exact mechanism depends on your data layer choice:

- **AWS AppSync + DynamoDB:** Use a script that batch-write items to the tables
- **Hasura + Postgres:** Use a SQL `INSERT` script generated from the JSON
- **Custom GraphQL server:** Use the GraphQL `createTitle`, `createAdTrack` mutations

### 2. Validate your data layer's resolvers

Run a test suite that:
- Loads each sample
- Queries the data layer for the same item
- Verifies the returned item matches the sample (modulo fields the schema doesn't expose)

This catches bugs where the resolver misnames a field, gets the type wrong, or misses a field.

### 3. Test your admin portal UI

Render the admin portal with the sample data. Verify:
- The titles page shows the titles
- The categories page shows the categories
- The feedback page shows the feedback
- The notification page shows the notifications

This catches UI bugs that don't show up in API tests.

### 4. Onboard new contributors

New contributors can read the samples to understand what real data looks like. This is faster than reading the schema alone.

---

## License

These sample files are released under **CC-BY-4.0**. You can use them, modify them, redistribute them — just credit this repository.

---

## Contributing improvements

If you add sample data that's useful for testing, please contribute it back. Open a PR with:

- The new sample file in this directory
- An update to this README explaining what the sample is for
- A note about what was redacted
