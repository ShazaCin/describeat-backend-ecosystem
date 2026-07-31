# Contributing to DescribeAT

Thank you for your interest in making DescribeAT better. The project is open-sourced under **AGPLv3 + DCO** to ensure improvements flow back to the community.

---

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to uphold it. Report unacceptable behaviour to the maintainers via the contact methods in [SECURITY.md](SECURITY.md).

---

## What we welcome

- **Documentation fixes** — typos, broken links, unclear explanations, missing context. The lowest-friction contribution; the highest-leverage.
- **Architecture corrections** — if you deployed DescribeAT and found something the docs got wrong, tell us. We want the docs to reflect reality.
- **Alternative deployment recipes** — Terraform modules, Kubernetes manifests, Docker Compose files, non-AWS deployments. If you can deploy DescribeAT differently, write it up.
- **Translations** — the docs are in English. Translations to other languages improve accessibility of the documentation itself. (Audio description accessibility is the project's mission; docs accessibility is part of that.)
- **Schema improvements** — if you have a more general way to express the data model, propose it.
- **Diagram updates** — the SVGs in `diagrams/` are hand-authored. If you find a clearer way to express an architecture concept, propose it.
- **Sample data** — more anonymised sample data helps deployers validate their setups.

## What we do NOT accept

- **Real production data, even anonymised.** Sample data must be obviously synthetic. No real title names, no real user emails, no real narrators.
- **Code that depends on closed-source libraries we don't have rights to.** If you want to integrate a new fingerprinting library, the integration code is welcome; the library itself must be open-source or documented as an external dependency.
- **Documentation that leaks production identifiers.** Use placeholders like `<your-account-id>`, `<your-domain>`, `us-east-1_XXXXXXXXX`. Never commit real AWS account IDs, Cognito pool IDs, etc.
- **Marketing material for specific products or services.** This is technical documentation, not a platform for promotion.

---

## The contribution workflow

### 1. Fork or branch

If you have write access, create a branch. If not, fork the repository.

Branch names should be descriptive:

- `docs/fix-typo-in-data-model`
- `docs/add-terraform-deployment-recipe`
- `examples/add-cognito-terraform`

### 2. Make your changes

Follow the existing style:

- **Markdown:** Sentence case headings, two-space indent, no trailing whitespace.
- **JSON:** Two-space indent, no comments (use `.json.md` files with code fences if comments are needed).
- **SVG:** Hand-authored, dark theme, labels on every box and arrow.
- **Examples:** Use placeholders like `<your-account-id>`, `example.com`, `us-east-1_XXXXXXXXX`. Never use real values.

### 3. Sign off (DCO)

This project uses the [Developer Certificate of Origin](https://developercertificate.org/). Every commit must be signed off:

```bash
git commit -s -m "docs: clarify the two-pool auth model"
```

The `-s` flag adds a `Signed-off-by:` line to your commit message, certifying that you have the right to submit the contribution under the project's license.

### 4. Open a merge request

MRs should include:

- A descriptive title (e.g. "docs: add Kubernetes deployment recipe" not "Update README")
- A description of what changed and why
- A reference to any related issues

If your MR is a documentation change, link to the specific file(s) you changed. If your MR is a code change (example scripts, etc.), include a way to test it.

### 5. CI checks

CI runs on every push and merge request via GitLab CI (see `.gitlab-ci.yml`):

- **Markdown lint** — checks for style violations
- **Link check** — verifies all links resolve
- **Secret scan** — verifies no real AWS IDs, API keys, etc. are present
- **JSON validation** — for any data files
- **SVG validation** — for any diagram changes

Some checks are set to `allow_failure: true` (they report but don't block the MR). The secret scan and JSON validation are blocking — if they fail, the MR cannot merge.

If CI fails, fix the issues. If CI is wrong, open an issue explaining.

### 6. Review

A maintainer will review your PR within 5 business days. They may:

- Approve and merge
- Approve with minor changes (they'll fix and merge)
- Request changes (you'll fix and re-request review)
- Reject (with a clear explanation)

Reviews are about correctness, clarity, and consistency with the existing docs. They're not about personal preference.

### 7. Merge

Once approved, the maintainer will merge. Your contribution is now part of the project.

---

## The DCO sign-off explained

The DCO is a lightweight alternative to a Contributor License Agreement (CLA). It certifies that:

1. You created the contribution, OR
2. You have the right to submit it under the project's license, OR
3. You understand that the contribution may be publicly available under the project's license

The full DCO text: https://developercertificate.org/

To sign off, add `-s` to your commit:

```bash
git commit -s -m "Your commit message"
```

This adds:

```
Signed-off-by: Your Name <[email protected]>
```

You can configure git to do this automatically:

```bash
git config --global format.signOff true
```

---

## What happens to your contribution

Your contribution is published under the AGPLv3 license. The full text is in [LICENSE](LICENSE). By signing off, you agree to this.

Your contribution is publicly available on GitLab. The commit history is preserved. The contribution may be redistributed as part of the project.

You retain copyright on your contribution. The AGPLv3 license grants others the right to use it under the project's terms; it does not transfer ownership.

---

## Reporting issues

If you find a bug in the documentation, have a question, or want to discuss a change before making it:

1. **Search existing issues** to see if it's already reported
2. **Open a new issue** with a clear title and description
3. **Tag appropriately** (documentation, question, bug, etc.)

For security issues, do **not** open a public issue. See [SECURITY.md](SECURITY.md).

---

## Becoming a maintainer

If you make significant contributions over time, you may be invited to become a maintainer. Maintainers:

- Review and merge PRs
- Triage issues
- Cut releases
- Make architectural decisions

Maintainer status is granted by the existing maintainers based on sustained, high-quality contributions. It is not automatic.

---

## Questions?

If you have a question that's not answered here:

- Check the [docs/](docs/) directory
- Check existing issues
- Open a new issue with the "question" label

We'll do our best to help.

---

Thank you for contributing. The project is better because of people like you.
