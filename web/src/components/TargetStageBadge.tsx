import type { TargetStage } from "@/lib/types";

const STAGE_STYLES: Record<TargetStage, string> = {
  planned: "bg-slate-100 text-slate-700 border-slate-300",
  contacted: "bg-blue-50 text-blue-700 border-blue-300",
  proposal_sent: "bg-indigo-50 text-indigo-700 border-indigo-300",
  meeting: "bg-violet-50 text-violet-700 border-violet-300",
  won: "bg-emerald-50 text-emerald-700 border-emerald-300",
  lost: "bg-rose-50 text-rose-700 border-rose-300",
};

const STAGE_LABEL: Record<TargetStage, string> = {
  planned: "Planned",
  contacted: "Contacted",
  proposal_sent: "Proposal sent",
  meeting: "Meeting",
  won: "Won",
  lost: "Lost",
};

export default function TargetStageBadge({ stage }: { stage: TargetStage }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STAGE_STYLES[stage]}`}
    >
      {STAGE_LABEL[stage]}
    </span>
  );
}
