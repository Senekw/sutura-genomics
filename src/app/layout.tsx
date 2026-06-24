import type { Metadata } from "next";
import { Jost } from "next/font/google";
import "./globals.css";

const jost = Jost({
  variable: "--font-jost",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Sutura Genomics — The alignment layer for spatial transcriptomics",
  description:
    "Sutura Genomics is building graph deep-learning infrastructure for aligning spatial transcriptomics tissue slices — designed for the tears and discontinuities that optimal-transport methods can't represent.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${jost.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
