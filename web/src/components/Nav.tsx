"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Tab = {
  href: string;
  label: string;
  match?: (pathname: string) => boolean;
};

const TABS: Tab[] = [
  { href: "/", label: "Home", match: (p) => p === "/" },
  { href: "/news", label: "Daily News" },
  { href: "/discover", label: "Discovery" },
  { href: "/targets", label: "Targets" },
  { href: "/proposals", label: "Proposals" },
  { href: "/rag", label: "RAG Docs" },
  { href: "/interactions", label: "사업 기록" },
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
                ? "rounded-md bg-slate-900 px-3 py-1.5 font-medium text-white"
                : "rounded-md px-3 py-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
            }
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
