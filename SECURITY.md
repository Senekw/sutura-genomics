# Security Policy

## Reporting a vulnerability

If you believe you have found a security issue in the Sutura Genomics website or
infrastructure, please email **suturagenomics@gmail.com** with:

- a description of the issue and its potential impact,
- steps to reproduce (proof-of-concept where possible),
- any relevant URLs, requests, or screenshots.

A machine-readable contact is published at `/.well-known/security.txt`.

## Our commitment

- We aim to acknowledge reports within **3 business days**.
- We aim to provide a remediation timeline within **10 business days**.
- We will keep you updated on progress and credit you if you wish.

We do not currently run a paid bug-bounty program, but we are grateful for
responsible disclosure and will recognize valid reports.

## Safe harbor / testing guidelines

We will not pursue or support legal action against researchers who, in good faith:

- test only against assets they are authorized to (this site and its public
  endpoints),
- avoid privacy violations, data destruction, and service degradation,
- do **not** run automated high-volume scans or denial-of-service tests,
- do **not** access, modify, or exfiltrate data that is not their own,
- give us a reasonable chance to remediate before public disclosure.

## In scope

- The marketing site and the demo-request form.
- The Supabase project backing the demo form (note: the public anon key is
  intentionally exposed and constrained to insert-only by Row Level Security).

## Out of scope

- Findings that require a compromised end-user device or browser.
- Reports from automated tools without a demonstrated, reproducible impact.
- Social engineering of staff or third parties.
- Volumetric / denial-of-service testing.

## Current posture

This is a static site (no user accounts, sessions, server runtime, or file
uploads). See `docs/security-roadmap.md` for what is implemented today and what
is planned as the product matures.
