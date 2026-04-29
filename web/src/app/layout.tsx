import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "BD Cold-Call Agent",
  description: "Search, summarize, and draft proposals for target companies.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-4 md:flex-row md:items-center md:justify-between">
            <Link href="/" className="text-lg font-semibold">
              BD Cold-Call Agent
            </Link>
            <Nav />
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
