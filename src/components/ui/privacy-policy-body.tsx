import {
  LAST_UPDATED,
  POLICY_INTRO,
  POLICY_SECTIONS,
  PRIVACY_EMAIL,
} from "@/lib/privacyPolicy";

// Turns the one email address that appears throughout the policy into a mailto
// link, leaving the surrounding prose untouched.
function withEmailLinks(text: string) {
  const parts = text.split(PRIVACY_EMAIL);
  if (parts.length === 1) return text;

  return parts.flatMap((part, i) =>
    i === 0
      ? [part]
      : [
          <a
            key={i}
            href={`mailto:${PRIVACY_EMAIL}`}
            className="text-[#6633ee] underline underline-offset-2 hover:no-underline"
          >
            {PRIVACY_EMAIL}
          </a>,
          part,
        ],
  );
}

/**
 * The policy text itself, shared by the footer modal and the /privacy page so
 * the two can never fall out of sync. Layout (headings, padding, scrolling) is
 * the caller's responsibility.
 */
export function PrivacyPolicyBody({ className }: { className?: string }) {
  return (
    <div className={className}>
      <p className="text-sm font-light leading-relaxed text-muted-foreground">
        {POLICY_INTRO}
      </p>

      <div className="mt-6 space-y-6">
        {POLICY_SECTIONS.map((section) => (
          <section key={section.title}>
            <h3 className="mb-1.5 text-sm font-semibold text-foreground">
              {section.title}
            </h3>

            {section.body?.map((paragraph, i) => (
              <p
                key={i}
                className="mb-2 text-sm font-light leading-relaxed text-muted-foreground last:mb-0"
              >
                {withEmailLinks(paragraph)}
              </p>
            ))}

            {section.bullets && (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm font-light leading-relaxed text-muted-foreground">
                {section.bullets.map((item, i) => (
                  <li key={i}>{withEmailLinks(item)}</li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>

      <p className="mt-8 border-t border-border pt-4 text-xs font-light leading-relaxed text-muted-foreground">
        Last updated: {LAST_UPDATED}
      </p>
    </div>
  );
}
