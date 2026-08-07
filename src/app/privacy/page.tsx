import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Logo } from "@/components/logo";
import { PrivacyPolicyBody } from "@/components/ui/privacy-policy-body";
import { LAST_UPDATED } from "@/lib/privacyPolicy";

export const metadata: Metadata = {
  title: "Privacy Policy — Sutura Genomics",
  description:
    "What Sutura Genomics collects, why, who processes it, and how to exercise your rights.",
};

export default function PrivacyPage() {
  return (
    <main className="relative mx-auto w-full max-w-2xl px-6 py-16 sm:py-20">
      <div className="mb-10 flex items-center justify-between">
        <Link
          href="/"
          className="flex items-center gap-1.5 text-sm font-light text-foreground/60 transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <Logo size={26} withWordmark wordmarkClassName="text-base" />
      </div>

      <h1 className="text-3xl font-light tracking-tight text-foreground">
        Privacy Policy
      </h1>
      <p className="mt-1.5 text-sm font-light text-muted-foreground">
        Last updated: {LAST_UPDATED}
      </p>

      <PrivacyPolicyBody className="mt-10" />
    </main>
  );
}
