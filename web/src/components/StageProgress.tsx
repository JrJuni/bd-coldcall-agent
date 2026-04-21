import { PIPELINE_STAGES } from "@/lib/types";

export function StageProgress({
  stagesCompleted,
  currentStage,
  failedStage,
}: {
  stagesCompleted: string[];
  currentStage: string | null;
  failedStage: string | null;
}) {
  const completed = new Set(stagesCompleted);
  return (
    <ol className="space-y-1 text-sm">
      {PIPELINE_STAGES.map((stage) => {
        const isDone = completed.has(stage);
        const isCurrent = currentStage === stage && !isDone;
        const isFailed = failedStage === stage;
        let icon = "○";
        let cls = "text-slate-400";
        if (isFailed) {
          icon = "✕";
          cls = "text-red-600 font-semibold";
        } else if (isDone) {
          icon = "✓";
          cls = "text-emerald-600";
        } else if (isCurrent) {
          icon = "●";
          cls = "text-sky-600 font-semibold animate-pulse";
        }
        return (
          <li key={stage} className={cls}>
            {icon} {stage}
          </li>
        );
      })}
    </ol>
  );
}
