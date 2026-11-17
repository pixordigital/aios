# AIOS customer viability dogfood

- Target: `http://127.0.0.1:8777`
- Date: 2026-11-17
- Browser: agent-browser / Chromium, desktop and 390×844 viewport
- Scope: public and pre-authentication experience only
- Account: none provided; customer workflows behind login were not exercised

## Summary

The local service is live and serves the AIOS login page. The page states that
signups are temporarily closed, which matches the repository's current
internal-tool pivot. The login form and optional 2FA disclosure are present and
the 2FA control expands to show a code field.

This run does **not** establish business viability. Without a dedicated
non-production business account, it was not possible to test onboarding,
agent setup, channel connection, approval handling, or whether a business gets
a useful outcome from the product. No authenticated or state-changing customer
actions were performed.

## Personas and journeys that remain untested

1. **Small-business owner:** sign in, configure a sales agent, connect a
   channel, and determine whether it can handle a real lead safely.
2. **Sales manager:** review agent replies, hand off uncertain/high-value work,
   and see whether CRM updates and follow-ups are dependable.
3. **Operations/finance owner:** inspect approvals, contracts, cost per unit of
   work, and measured outcomes to decide whether the system is controllable and
   worth paying for.

## Findings

### ISSUE-001 — Login text fails automated contrast checks

- Severity: Serious (axe classification)
- Page: `/dashboard/login`
- Evidence: [desktop login](screenshots/login-initial.png),
  [mobile login](screenshots/login-mobile.png)
- Reproduction: Open `/dashboard/login`; run the page accessibility audit.
- Result: axe 4.12.1 reports a `color-contrast` violation on five nodes:
  `.subtitle`, both form labels, the 2FA summary, and footer text. The mobile
  capture also shows these labels and supporting text as faint against the dark
  background.
- User impact: People with low vision or in bright environments may struggle
  to read instructions and labels while signing in.

### ISSUE-002 — Login page has no main landmark or level-one heading

- Severity: Moderate (axe classification)
- Page: `/dashboard/login`
- Evidence: [desktop login](screenshots/login-initial.png)
- Reproduction: Open `/dashboard/login`; run the page accessibility audit.
- Result: axe reports `landmark-one-main`, `page-has-heading-one`, and `region`
  violations. The visible “Acesse sua conta” text is not exposed as a level-one
  heading, and page content is not organized into landmark regions.
- User impact: Screen-reader users have fewer reliable navigation landmarks and
  cannot jump to a clear page heading.

## Checks completed

- `/health/live` returned HTTP 200 with `{"status":"live"}`.
- Login page loaded and fit a 390×844 viewport.
- Optional 2FA control expanded and exposed a code input.
- Automated accessibility audit: 4 violation rules, 16 passes, 0 incomplete.
- Signup is unavailable on this instance; no attempt was made to bypass it.

## Blocker to completing the business simulation

Provide a dedicated non-production business account, or an isolated test
environment with a supported way to create one. Then repeat the three journeys
above with realistic business data and verify both successful outcomes and
failure/approval paths.
