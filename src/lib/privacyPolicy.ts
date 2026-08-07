// Privacy policy content, shared by the footer modal and the standalone
// /privacy page so the two can never drift apart.
//
// Every factual claim here is tied to actual behaviour in this repository:
//   - demo form fields ............ src/app/demo/page.tsx (FormState)
//   - form delivery ............... Web3Forms, src/app/demo/page.tsx
//   - .h5ad upload ................ src/lib/h5adUpload.ts, netlify/functions/upload.mjs
//   - analysis assistant .......... netlify/functions/chat.mjs (Google Gemini)
//   - browser storage ............. src/lib/demoAuth.ts, demoRuns.ts, demoSettings.ts
//   - IP-based rate limiting ...... netlify/functions/chat.mjs
// If any of those change, update this file in the same commit.

export const LAST_UPDATED = "7 August 2026";
export const PRIVACY_EMAIL = "suturagenomics@gmail.com";

export type PolicySection = {
  title: string;
  /** Paragraphs of prose. */
  body?: string[];
  /** Bulleted items, rendered after the paragraphs. */
  bullets?: string[];
};

export const POLICY_INTRO =
  "This policy explains what Sutura Genomics collects when you use this website " +
  "or its product demo, why we collect it, who processes it on our behalf, and " +
  "what you can ask us to do with it. It describes the site as it actually " +
  "behaves today; where a feature does not collect something, we say so.";

export const POLICY_SECTIONS: PolicySection[] = [
  {
    title: "Who we are",
    body: [
      "Sutura Genomics ([legal entity name], [registered address]) is the data " +
        "controller for the information described in this policy. You can reach " +
        `us about any privacy matter at ${PRIVACY_EMAIL}.`,
    ],
  },
  {
    title: "Information you give us",
    body: [
      "The demo request form is the only place on this site where we ask you for " +
        "personal information. It collects:",
    ],
    bullets: [
      "your full name;",
      "your email address;",
      "your company or institution;",
      "your role (optional);",
      "your organisation's size;",
      "what you are looking to do with spatial alignment;",
      "how you heard about us (optional).",
    ],
  },
  {
    title: "Research data you upload",
    body: [
      "The demo workspace lets you upload an AnnData (.h5ad) file. Because such " +
        "files can contain sensitive research data, we are specific about what " +
        "happens to one:",
      "Your browser reads the file locally to determine its spot count — that " +
        "parsing never leaves your machine. Files of 5 MB or less are then sent in " +
        "full to our upload endpoint. For larger files, only the first 64 KB — the " +
        "HDF5 header, enough to confirm the file is genuinely HDF5 — is sent, " +
        "along with the file's name, size, and spot count.",
      "The endpoint validates the file signature, writes it to the temporary " +
        "storage of a serverless function instance, and confirms receipt. We do " +
        "not move uploads into permanent storage, add them to a database, use them " +
        "to train or evaluate models, or share them with anyone. That temporary " +
        "storage is ephemeral and is discarded when the function instance is " +
        "recycled.",
      "This is a demonstration feature, not a data-processing service. Please do " +
        "not upload identifiable patient data, protected health information, or " +
        "anything your institution's data-governance rules would not permit you to " +
        "send to a third-party demo environment.",
    ],
  },
  {
    title: "The analysis assistant",
    body: [
      "The demo's analysis assistant answers questions about an alignment result. " +
        "When you ask a question, the question text and the alignment metrics shown " +
        "on screen are sent to Google's Gemini API, which generates the answer. Do " +
        "not type anything into it that you would not want processed by Google.",
      "We do not send your name, email, or uploaded file contents to that API, and " +
        "we do not keep a record of your questions.",
    ],
  },
  {
    title: "Information collected automatically",
    body: [
      "Our hosting provider records standard technical data for every request, " +
        "including your IP address, the time of the request, the page or endpoint " +
        "requested, and your browser's user-agent string. This is ordinary server " +
        "logging, used to keep the site available and secure.",
      "Our chat endpoint also holds IP addresses briefly in memory to enforce rate " +
        "limits and prevent abuse. These are not written to disk and do not persist " +
        "beyond the running function instance.",
    ],
  },
  {
    title: "Cookies and browser storage",
    body: [
      "We use no tracking cookies, no advertising pixels, and no third-party " +
        "analytics. We do not track you across other websites.",
      "The demo does use your browser's own local and session storage to function. " +
        "This data stays in your browser, is never transmitted to us, and holds:",
    ],
    bullets: [
      "a flag recording that you are signed in to the demo;",
      "your saved alignment-run history;",
      "your demo preferences and settings;",
      "a counter used to rate-limit assistant requests.",
    ],
  },
  {
    title: "How we use your information",
    body: [
      "We use demo request details to respond to your enquiry, to arrange and " +
        "carry out a demo, and to follow up about it. Where you have asked to hear " +
        "from us, we may send occasional updates about Sutura Genomics; every such " +
        "message includes a way to opt out.",
      "We use technical and upload data to operate, secure, and debug the site. We " +
        "do not use any of it for automated decision-making or profiling, and we do " +
        "not sell, rent, or trade personal information.",
      "Where the UK/EU GDPR applies, our legal bases are your consent (for " +
        "submitting the form and receiving updates) and our legitimate interests in " +
        "responding to business enquiries and keeping the site secure.",
    ],
  },
  {
    title: "Who else processes your data",
    body: [
      "We keep this list short and name every processor rather than referring " +
        "vaguely to 'third parties'. Each acts on our instructions and does not " +
        "receive your data for its own marketing:",
    ],
    bullets: [
      "Netlify — hosts the site and runs its serverless functions, and therefore " +
        "processes all request traffic and server logs.",
      "Web3Forms — delivers demo request submissions to our inbox, and therefore " +
        "receives every field of the form.",
      "Google (Gemini API) — generates analysis assistant answers, and therefore " +
        "receives the questions you type there together with the on-screen metrics.",
    ],
  },
  {
    title: "International transfers",
    body: [
      "These providers operate in the United States, so your information may be " +
        "processed outside your country. Where the UK/EU GDPR applies, such " +
        "transfers rely on the providers' Standard Contractual Clauses or an " +
        "equivalent approved safeguard.",
    ],
  },
  {
    title: "How long we keep it",
    body: [
      "We keep demo request details for as long as we are in contact with you " +
        "about your enquiry and for up to 24 months afterwards, then delete them.",
      "Uploaded files persist only in a serverless function's ephemeral storage " +
        "and are discarded when that instance is recycled — typically within " +
        "minutes. Server logs follow our hosting provider's standard retention. " +
        "Browser storage stays until you clear your browser data.",
    ],
  },
  {
    title: "Security",
    body: [
      "The site is served over HTTPS with HSTS, a strict Content Security Policy, " +
        "and clickjacking and MIME-sniffing protections. API credentials are held " +
        "in server-side environment variables and are never exposed to the browser. " +
        "Uploads are validated by file signature before they are accepted.",
      "No system is perfectly secure, and we cannot guarantee absolute security. " +
        "If you believe you have found a vulnerability, please report it as " +
        "described in our security policy at /.well-known/security.txt.",
    ],
  },
  {
    title: "Your rights",
    body: [
      "Depending on where you live, you may have the right to access the personal " +
        "information we hold about you, correct it, delete it, restrict or object " +
        "to how we use it, receive it in a portable format, or withdraw consent at " +
        "any time. Withdrawing consent does not affect processing already carried " +
        "out.",
      `To exercise any of these, email ${PRIVACY_EMAIL}. We will respond within 30 ` +
        "days. We do not charge for this and will not treat you differently for " +
        "asking. If you are in the UK or EU and are unhappy with our response, you " +
        "may complain to your national data protection authority.",
      "We do not sell or share personal information as those terms are defined " +
        "under California law.",
    ],
  },
  {
    title: "Children",
    body: [
      "This site is intended for professional and business use. It is not directed " +
        "at children under 16, and we do not knowingly collect their personal " +
        "information. If you believe a child has provided us information, contact " +
        "us and we will delete it.",
    ],
  },
  {
    title: "Changes to this policy",
    body: [
      "If we change this policy we will update the date at the top. Material " +
        "changes affecting how we handle information you have already given us will " +
        "be notified by email where we hold an address for you.",
    ],
  },
  {
    title: "Contact",
    body: [
      `For any question, request, or complaint about privacy, email ${PRIVACY_EMAIL}.`,
    ],
  },
];
