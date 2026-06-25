"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check, ChevronDown } from "lucide-react";

import { Background } from "@/components/ui/background-snippets";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import PrivacyPolicyModal from "@/components/ui/privacy-policy-modal";
import { Logo } from "@/components/logo";
import { supabase } from "@/lib/supabase";

interface FormState {
  fullName: string;
  email: string;
  company: string;
  role: string;
  size: string;
  looking: string;
  source: string;
}

type Errors = Partial<Record<keyof FormState, string>>;

const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const sizes = ["1–10", "11–50", "51–200", "201–1,000", "1,000+"];

// Web3Forms emails each submission to the address the key is registered to.
// Public by design (client-side); abuse is limited by Web3Forms' spam filtering.
const WEB3FORMS_ACCESS_KEY = "31af204b-f37d-41d6-815f-e720fd494926";

export default function DemoPage() {
  const [v, setV] = useState<FormState>({
    fullName: "",
    email: "",
    company: "",
    role: "",
    size: "",
    looking: "",
    source: "",
  });
  const [errors, setErrors] = useState<Errors>({});
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const set =
    (key: keyof FormState) =>
    (
      e: React.ChangeEvent<
        HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
      >
    ) => {
      setV((s) => ({ ...s, [key]: e.target.value }));
      if (errors[key]) setErrors((p) => ({ ...p, [key]: undefined }));
    };

  const validate = () => {
    const next: Errors = {};
    if (!v.fullName.trim()) next.fullName = "Required.";
    if (!v.email.trim()) next.email = "Required.";
    else if (!emailRegex.test(v.email)) next.email = "Enter a valid email.";
    if (!v.company.trim()) next.company = "Required.";
    if (!v.size) next.size = "Required.";
    if (!v.looking.trim()) next.looking = "Required.";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setSubmitError(null);
    setSubmitting(true);

    // 1) Save the lead to Supabase (the source of truth).
    const { error } = await supabase.from("demo_requests").insert({
      full_name: v.fullName.trim(),
      email: v.email.trim(),
      company: v.company.trim(),
      role: v.role.trim() || null,
      company_size: v.size,
      looking_for: v.looking.trim(),
      source: v.source.trim() || null,
    });

    if (error) {
      setSubmitting(false);
      console.error("demo_requests insert failed:", error);
      setSubmitError(
        "Something went wrong saving your request. Please email us directly at rushilmaniar2010@gmail.com."
      );
      return;
    }

    // 2) Best-effort email notification via Web3Forms. Never block success on
    //    this — the lead is already saved in Supabase if the email fails.
    try {
      await fetch("https://api.web3forms.com/submit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          access_key: WEB3FORMS_ACCESS_KEY,
          subject: `New demo request — ${v.company.trim()}`,
          from_name: "Sutura Genomics website",
          name: v.fullName.trim(),
          email: v.email.trim(),
          company: v.company.trim(),
          role: v.role.trim() || "—",
          company_size: v.size,
          looking_for: v.looking.trim(),
          source: v.source.trim() || "—",
        }),
      });
    } catch (err) {
      console.error("web3forms email failed (lead is still saved):", err);
    }

    setSubmitting(false);
    setSubmitted(true);
  };

  return (
    <main className="relative flex min-h-screen flex-col items-center px-6 py-16">
      <Background />

      <Link
        href="/"
        className="absolute left-6 top-6 flex items-center gap-1.5 text-sm font-light text-foreground/60 transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>

      <div className="mt-6 w-full max-w-md">
        <div className="mb-7 flex flex-col items-center text-center">
          <Logo size={40} withWordmark={false} className="mb-4" />
          <h1 className="text-xl font-light tracking-tight text-foreground">
            Get in touch
          </h1>
          <p className="mt-1.5 text-sm font-light text-muted-foreground">
            Tell us a bit about you and the tissue you work with — we&rsquo;ll be
            in touch.
          </p>
        </div>

        {submitted ? (
          <div className="flex flex-col items-center rounded-2xl border border-border bg-white/80 px-6 py-12 text-center backdrop-blur-sm">
            <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-[#6633ee]/10">
              <Check className="h-5 w-5 text-[#6633ee]" />
            </div>
            <p className="text-lg font-normal text-foreground">
              Thanks, {v.fullName.split(" ")[0]}.
            </p>
            <p className="mt-1.5 text-sm font-light text-muted-foreground">
              We&rsquo;ll reach out at{" "}
              <span className="text-foreground">{v.email}</span> shortly.
            </p>
            <Link href="/" className="mt-6">
              <Button variant="outline" size="sm" className="rounded-full">
                Back to home
              </Button>
            </Link>
          </div>
        ) : (
          <form
            onSubmit={onSubmit}
            noValidate
            className="rounded-2xl border border-border bg-white/80 p-6 backdrop-blur-sm sm:p-7"
          >
            <div className="flex flex-col gap-4">
              <Input
                label="Full name"
                required
                placeholder="Jane Doe"
                value={v.fullName}
                onChange={set("fullName")}
                error={errors.fullName}
                autoComplete="name"
              />
              <Input
                label="Work email"
                required
                type="email"
                placeholder="jane@institution.edu"
                value={v.email}
                onChange={set("email")}
                error={errors.email}
                autoComplete="email"
              />
              <Input
                label="Company"
                required
                placeholder="University / Lab / Company"
                value={v.company}
                onChange={set("company")}
                error={errors.company}
                autoComplete="organization"
              />
              <Input
                label="Your role"
                placeholder="e.g. Principal Investigator"
                value={v.role}
                onChange={set("role")}
                autoComplete="organization-title"
              />

              {/* Company size — native select styled to match */}
              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="size"
                  className="text-[13px] text-muted-foreground"
                >
                  Company size
                  <span className="ml-0.5 text-foreground/40">*</span>
                </label>
                <div className="relative">
                  <select
                    id="size"
                    value={v.size}
                    onChange={set("size")}
                    aria-invalid={Boolean(errors.size)}
                    className={`h-11 w-full appearance-none rounded-lg border bg-white px-3.5 pr-9 text-sm outline-none transition-all duration-150 focus:ring-2 focus:ring-ring/20 ${
                      v.size ? "text-foreground" : "text-muted-foreground/50"
                    } ${
                      errors.size
                        ? "border-destructive"
                        : "border-input hover:border-muted-foreground/40 focus:border-ring"
                    }`}
                  >
                    <option value="" disabled>
                      Select…
                    </option>
                    {sizes.map((s) => (
                      <option key={s} value={s} className="text-foreground">
                        {s}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                </div>
                {errors.size && (
                  <span className="text-[12.5px] text-destructive">
                    {errors.size}
                  </span>
                )}
              </div>

              <Textarea
                label="What are you looking for?"
                required
                placeholder="What you’re hoping Sutura can help with, current alignment tools, sample types…"
                value={v.looking}
                onChange={set("looking")}
                error={errors.looking}
              />
              <Input
                label="How did you hear about us?"
                placeholder="Optional"
                value={v.source}
                onChange={set("source")}
              />

              <Button
                type="submit"
                size="lg"
                disabled={submitting}
                className="mt-1 h-12 w-full rounded-full text-[15px]"
              >
                {submitting ? "Submitting…" : "Submit"}
              </Button>

              {submitError && (
                <p className="text-center text-[13px] font-light text-destructive">
                  {submitError}
                </p>
              )}

              <p className="text-center text-[12px] font-light leading-relaxed text-muted-foreground">
                By submitting, you agree to our{" "}
                <PrivacyPolicyModal
                  trigger={
                    <button
                      type="button"
                      className="text-foreground/70 underline underline-offset-2 hover:text-foreground"
                    >
                      Privacy Policy
                    </button>
                  }
                />
                . This form is for business inquiries and is not intended for
                children under 13.
              </p>
            </div>
          </form>
        )}
      </div>
    </main>
  );
}
