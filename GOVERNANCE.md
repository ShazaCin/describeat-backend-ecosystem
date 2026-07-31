# Governance

> **DescribeAT is operated by Shazacin. This document describes how the open-source project is governed alongside Shazacin's continued ownership of the canonical service.**

---

## The project in one paragraph

DescribeAT is an audio-description sync app for blind and visually impaired users. It was built and operated as a closed commercial product by Shazacin. In 2026, Shazacin decided to release the application code under AGPLv3 so the blind and VI community can contribute fixes, improvements, and new features. This repository is the sanitised public release of the listener-facing PWA. It is one of three open-source repos that make up the DescribeAT system (the others are [describeat-admin-public](https://github.com/ShazaCin/describeat-admin-public) and [describeat-backend-ecosystem](https://github.com/ShazaCin/describeat-backend-ecosystem)).

## Tier model: Contributor → Committer → Maintainer

DescribeAT follows a three-tier governance model standard in well-run open-source projects.

### Contributor

Anyone who opens issues, sends pull requests, files bug reports, writes documentation, helps other users in Discussions, or in any other way contributes to the project. No formal application. Contributions are licensed under AGPLv3 + DCO (see [CONTRIBUTING.md](CONTRIBUTING.md)).

### Committer

Trusted contributors who can merge non-controversial pull requests directly: typo fixes, dependency version bumps that pass CI, code refactors that don't change behaviour, documentation corrections, test additions.

Promotion to Committer happens by **existing Maintainer nomination + no objection from any other Maintainer** after the contributor has demonstrated sustained, high-quality contributions over time. There is no fixed number of PRs or time period — quality and judgment matter more than volume.

### Maintainer

Trusted contributors who can merge architectural changes, dependency additions, schema changes, and any change affecting public APIs, data models, or trademark usage. The Maintainer tier carries final say within the project's scope.

There are typically a small number of Maintainers. The roster is curated by Shazacin via BGC.

## Shazacin's veto

**Shazacin retains full commercial rights and has final say on changes that affect the public-facing listener experience.** Specifically:

- Architectural changes to the sync engine or audio playback pipeline
- Additions of new third-party dependencies (privacy, security, and licensing implications)
- Changes to the data model shared with the backend ecosystem
- Anything affecting the DescribeAT or Shazacin trademark usage

Maintainers flag these decisions to Shazacin (via BGC) before merging. Shazacin's veto is exercised only on the items above — it is **not** a blanket approval gate on every PR. Routine changes (bug fixes, docs, tests) flow through Committer approval without Shazacin involvement.

## What Shazacin does **not** control

Shazacin does not review or veto:

- Bug fixes that don't change the public API
- Documentation and translation contributions
- Test additions
- Internal refactors that don't change observable behaviour
- Accessibility improvements (Shazacin actively welcomes these — they're the primary audience)

If a Committer is uncertain whether a change falls under the veto, they should mark it for Maintainer review rather than guess.

## Conflict resolution

1. **First, talk.** Most disagreements resolve when participants read each other's actual positions rather than their assumed positions. Use the relevant GitHub Issue or Discussion.
2. **Escalate to Maintainers** if talking doesn't resolve it. A Maintainer who is a party to the conflict should recuse themselves from the decision.
3. **Escalate to Shazacin via BGC** if Maintainers cannot reach consensus on an architectural question. Shazacin's decision is final within the project's scope.

## Trademark

The DescribeAT and Shazacin names and logos are trademarks of Shazacin. The open-source release grants you the right to use, modify, and distribute the **code** under AGPLv3. It does not grant you the right to use the DescribeAT name or logo in a way that suggests Shazacin endorses your derivative product. See [TRADEMARK.md](TRADEMARK.md).

## Code of Conduct enforcement

Code of Conduct violations are handled by Maintainers in consultation with Shazacin. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the standards and the reporting process.

## Changes to this document

Changes to GOVERNANCE.md require Maintainer approval and a public comment period of at least 7 days before merging.