"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Tab = {
  href: string;
  label: string;
  match?: (pathname: string) => boolean;
  // Phase 13 — surfaces that have migrated to Notion as their primary
  // workspace get a small "legacy" pill so users know the Web UI view
  // is observability-only.
  legacy?: boolean;
};

const TABS: Tab[] = [
  { href: "/", label: "Home", match: (p) => p === "/" },
  { href: "/news", label: "Daily News" },
  { href: "/discover", label: "Discovery" },
  { href: "/targets", label: "Targets", legacy: true },
  { href: "/proposals", label: "Proposals" },
  { href: "/rag", label: "RAG Docs" },
  { href: "/interactions", label: "사업 기록", legacy: true },
  { href: "/cost", label: "Cost" },
  { href: "/settings", label: "Settings" },
];

function isActive(pathname: string, tab: Tab): boolean {
  if (tab.match) return tab.match(pathname);
  return pathname === tab.href || pathname.startsWith(tab.href + "/");
}

export default function Nav() {
  const pathname = usePathname() ?? "/";
  return (
    <nav className="flex flex-wrap gap-1 text-sm">
      {TABS.map((tab) => {
        const active = isActive(pathname, tab);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={
              active
                ? "inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 font-medium text-white"
                : "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            }
          >
            <span>{tab.label}</span>
            {tab.legacy && (
              <span
                title="Legacy / observability view — primary workspace is Notion"
                className={
                  active
                    ? "rounded-sm bg-white/20 px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white/80"
                    : "rounded-sm bg-slate-200 px-1 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500"
                }
              >
                legacy
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
