"use client";

import Image from "next/image";
import Link from "next/link";

import { Typewriter } from "@/components/ui/typewriter-text";
import PrivacyPolicyModal from "@/components/ui/privacy-policy-modal";

const founders = [
  {
    name: "Rushil Maniar",
    role: "Co-founder & CEO",
    email: "suturagenomics@gmail.com",
  },
  { name: "Sean Lee", role: "Co-founder & CTO", email: "syandsy@gmail.com" },
];

export default function Home() {
  return (
    <main className="landing">
      {/* Discreet entry point to the product demo (top-right corner) */}
      <Link
        href="/demo/login"
        className="fade d1 fixed right-6 top-6 z-10 text-[14px] font-light text-[#8a8a8a] transition-colors hover:text-[#111]"
        style={{ letterSpacing: "0.02em" }}
      >
        Sign in
      </Link>

      {/* Logo lockup — emblem + wordmark */}
      <div className="brand fade d1">
        <Image
          src="/sutura-logo.png"
          alt="Sutura Genomics"
          width={46}
          height={46}
          priority
          className="mark"
          style={{ width: 46, height: 46 }}
        />
        <span className="word">Sutura Genomics</span>
      </div>

      {/* Tagline — typewriter (honest, no benchmark claim) */}
      <p className="tagline fade d1">
        <Typewriter
          text={[
            "The alignment layer for spatial transcriptomics",
            "Graph deep learning for tissue registration",
            "Built for the tears optimal transport can't represent",
          ]}
          speed={55}
          deleteSpeed={28}
          delay={2400}
          loop
          cursor="|"
        />
      </p>

      <Link className="btn fade d2" href="/demo">
        Book a demo
        <span className="arrow" aria-hidden="true">
          &rarr;
        </span>
      </Link>

      <div className="divider fade d3" />

      <div className="team fade d3">
        {founders.map((f) => (
          <div className="member" key={f.name}>
            <a href={`mailto:${f.email}`}>{f.name}</a>
            <div className="role">{f.role}</div>
          </div>
        ))}
      </div>

      <p className="foot fade d4">
        © 2026 Sutura Genomics &nbsp;·&nbsp;{" "}
        <PrivacyPolicyModal
          trigger={<button type="button">Privacy Policy</button>}
        />
      </p>
    </main>
  );
}
