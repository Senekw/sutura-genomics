"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "@/components/ui/dialog";

const sections = [
  {
    title: "What we collect",
    content:
      "When you request a demo, we collect your name, email address, and institution. We do not collect any other personal information.",
  },
  {
    title: "How we use it",
    content:
      "We use your information solely to contact you about your demo request and updates related to Sutura Genomics. We do not sell, rent, or share your information with third parties.",
  },
  {
    title: "Data storage",
    content:
      "Your information is stored securely. We retain it only as long as necessary to fulfill the purpose for which it was collected.",
  },
  {
    title: "Cookies",
    content:
      "Our website does not use tracking cookies or analytics tools.",
  },
  {
    title: "Your rights",
    content:
      "You can request deletion of your information at any time by emailing suturagenomics@gmail.com.",
  },
  {
    title: "Contact",
    content:
      "For any privacy-related questions: suturagenomics@gmail.com",
  },
];

export default function PrivacyPolicyModal({
  trigger,
}: {
  trigger?: React.ReactNode;
}) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        {trigger ?? (
          <button className="text-muted-foreground transition-colors hover:text-foreground">
            Privacy Policy
          </button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-h-[80vh]">
        <DialogHeader className="border-b border-border px-6 py-5">
          <DialogTitle className="text-xl">Privacy Policy</DialogTitle>
          <DialogDescription>Last updated: June 2026</DialogDescription>
        </DialogHeader>

        <div className="max-h-[55vh] space-y-5 overflow-y-auto px-6 pb-6 pt-1">
          {sections.map((section) => (
            <div key={section.title}>
              <p className="mb-1 text-sm font-semibold text-foreground">
                {section.title}
              </p>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {section.content.includes("@") ? (
                  <>
                    {section.content.split("suturagenomics@gmail.com")[0]}
                    <a
                      href="mailto:suturagenomics@gmail.com"
                      className="text-[#6633ee] hover:underline"
                    >
                      suturagenomics@gmail.com
                    </a>
                    {section.content.split("suturagenomics@gmail.com")[1]}
                  </>
                ) : (
                  section.content
                )}
              </p>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
