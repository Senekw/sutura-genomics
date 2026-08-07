"use client";

import Link from "next/link";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "@/components/ui/dialog";
import { PrivacyPolicyBody } from "@/components/ui/privacy-policy-body";
import { LAST_UPDATED } from "@/lib/privacyPolicy";

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
      <DialogContent className="sm:max-h-[85vh]">
        <DialogHeader className="border-b border-border px-6 py-5">
          <DialogTitle className="text-xl">Privacy Policy</DialogTitle>
          <DialogDescription>Last updated: {LAST_UPDATED}</DialogDescription>
        </DialogHeader>

        <PrivacyPolicyBody className="max-h-[60vh] overflow-y-auto px-6 pb-4 pt-1" />

        <div className="border-t border-border px-6 py-3">
          <Link
            href="/privacy"
            className="text-xs font-light text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground"
          >
            Open as a full page
          </Link>
        </div>
      </DialogContent>
    </Dialog>
  );
}
