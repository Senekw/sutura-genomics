# Security roadmap

A credible, honest account of where security stands today and how it scales as
the product grows. Target frameworks: **OWASP ASVS Level 2** and **NIST SSDF**,
adopted incrementally (not all at once on a brochure site).

## What the site is today

A **static** marketing site (Next.js static export on Netlify) plus a
demo-request form. There are **no** user accounts, sessions, server runtime,
file uploads, payments, or exposed model endpoints. The only data collected is
demo-request leads, written to a Supabase table that is insert-only for the
public.

This scope matters: most enterprise security controls protect things that do not
exist yet. Adding them now would be security theater. They are scheduled below
against the milestone that makes them real.

## Implemented now

| Area | Control |
|------|---------|
| Transport | HTTPS forced (Netlify) + HSTS preload |
| Headers | CSP, X-Frame-Options=DENY, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, CORP |
| Clickjacking | `frame-ancestors 'none'` + X-Frame-Options |
| Injection | Supabase client uses parameterized queries; no raw SQL; React auto-escaping; no `dangerouslySetInnerHTML` |
| Form abuse | Honeypot bot-trap; provider-side spam filtering (Web3Forms) |
| Data (DB) | Row Level Security (insert-only for public); server-side CHECK constraints (email shape + length bounds) |
| Secrets | No `service_role`/private keys in repo; only public-by-design keys committed (anon, publishable, Web3Forms) |
| Supply chain | Dependabot (npm + Actions, weekly); `npm audit` gate in CI; SBOM (CycloneDX) generated in CI |
| CI/CD | Security CI on every push/PR: build + `npm audit` (high) + gitleaks secret scan + SBOM |
| Disclosure | `SECURITY.md` + `/.well-known/security.txt` |
| Privacy | Privacy Policy (in-app); data-deletion contact |

## Threat model (current scope)

- **Assets:** demo-request leads (PII: name, work email, company); the domain and
  deploy pipeline; brand reputation.
- **Actors:** spam/scraper bots; opportunistic web attackers; account/domain
  takeover attempts.
- **Surfaces:** the public form (→ Supabase + Web3Forms); the GitHub repo +
  Netlify deploy; DNS/registrar.
- **Primary mitigations:** RLS insert-only + DB constraints; honeypot; security
  headers; least-secret-exposure; CI secret scan; (pending) repo + DNS hardening.

## Action items NOT in code (do these in dashboards)

- **GitHub repo settings:** enable branch protection on `main` (require PR +
  review, require Code Owners via `.github/CODEOWNERS`), enable **secret scanning
  + push protection**, restrict who can merge. Consider required signed commits.
- **DNS / registrar:** registrar MFA, domain lock, certificate-expiry monitoring,
  and (if sending mail from the domain) **SPF + DKIM + DMARC**; DNSSEC if
  supported.
- **Netlify:** restrict deploy/admin access with MFA; protect environment vars.
- **Dependencies:** triage the known moderate `npm audit` finding (build-time
  postcss in Next) on the next deliberate Next upgrade.

## Scheduled by milestone

| Becomes real when you… | Then implement |
|---|---|
| Add user accounts / login | Argon2id hashing, email verification, MFA/passkeys, generic auth errors, login rate-limit + lockout, session rotation/revocation, breach-password checks |
| Add a backend API + customer data | Server-side authz on every endpoint (RBAC + object-ownership), tenant isolation, input/schema validation (Zod), API rate limits, idempotency, audit logging |
| Stand up infrastructure | Private networking/VPC, WAF, DDoS protection, encryption at rest, IAM least-privilege, no long-lived creds, cloud audit logs, monitoring/alerting, tested backups + DR |
| Let users upload files (slides, h5ad) | Size/MIME validation, virus scan, re-encoding/sandboxing, random filenames, storage outside web root |
| Expose the model as a service | Prompt-injection defenses, output validation, model/token rate limits, no direct command/DB execution from model output, uploaded-file scanning |
| Accept payments | Tokenization (never store cards), webhook signature verification, idempotency keys, replay protection |
| Sell to biotech / hospitals / EU | SOC 2 and likely HIPAA (if PHI), GDPR/CCPA, ISO 27001; written policies (IR, access control, retention, vendor mgmt); SSO (SAML/OIDC), SCIM, audit logs, data residency |

## Process (Secure SDLC, adopt incrementally)

- Threat-model new features before building; security review on risky changes.
- Every PR: review (CODEOWNERS), lint, build, dependency + secret scan (CI).
- Pen test before major releases once a real backend exists.
- Keep this document and a data-flow diagram current.
