"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Background } from "@/components/ui/background-snippets";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/logo";
import { checkCredentials, signIn } from "@/lib/demoAuth";

export default function DemoLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!checkCredentials(email, password)) {
      setError("Those credentials aren't recognized. Check your email and password and try again.");
      return;
    }

    setSubmitting(true);
    signIn();
    router.push("/demo/dashboard");
  };

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center px-6 py-16">
      <Background />

      <Link
        href="/"
        className="absolute left-6 top-6 flex items-center gap-1.5 text-sm font-light text-foreground/60 transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>

      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo size={44} withWordmark className="mb-6" />
          <h1 className="text-xl font-light tracking-tight text-foreground">
            Sign in to your workspace
          </h1>
          <p className="mt-1.5 text-sm font-light text-muted-foreground">
            Spatial alignment for your tissue sections.
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          noValidate
          className="rounded-2xl border border-border bg-white/80 p-6 backdrop-blur-sm sm:p-7"
        >
          <div className="flex flex-col gap-4">
            <Input
              label="Email"
              type="text"
              placeholder="you@lab.org"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                if (error) setError(null);
              }}
              error={Boolean(error)}
              autoComplete="username"
              autoFocus
            />
            <Input
              label="Password"
              type="password"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (error) setError(null);
              }}
              error={Boolean(error)}
              autoComplete="current-password"
            />

            {error && (
              <p className="text-[12.5px] font-light leading-relaxed text-destructive">
                {error}
              </p>
            )}

            <Button
              type="submit"
              size="lg"
              disabled={submitting}
              className="mt-1 h-12 w-full rounded-full bg-[#6633ee] text-[15px] text-white shadow-sm shadow-[#6633ee]/20 hover:bg-[#5a2ce0]"
            >
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </div>
        </form>

        <p className="mt-5 text-center text-[12px] font-light leading-relaxed text-muted-foreground">
          This is a guided product demo.{" "}
          <Link
            href="/demo"
            className="text-foreground/70 underline underline-offset-2 hover:text-foreground"
          >
            Request full access
          </Link>
          .
        </p>
      </div>
    </main>
  );
}
