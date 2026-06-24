import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static HTML export — Netlify serves the generated `out/` folder directly.
  // No serverless runtime needed (the site is fully client/static).
  output: "export",
  // next/image can't use the optimization server in a static export.
  images: { unoptimized: true },
};

export default nextConfig;
