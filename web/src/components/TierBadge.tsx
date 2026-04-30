import type { Tier } from "@/lib/types";

const STYLES: Record<Tier, string> = {
  S: "bg-amber-100 text-amber-800 border-amber-300",
  A: "bg-emerald-100 text-emerald-800 border-emerald-300",
  B: "bg-sky-100 text-sky-800 border-sky-300",
  C: "bg-slate-100 text-slate-700 border-slate-300",
};

export default function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span
      className={`inline-flex h-6 w-6 items-center justify-center rounded border text-xs font-bold ${STYLES[tier]}`}
    >
      {tier}
    </span>
  );
}
