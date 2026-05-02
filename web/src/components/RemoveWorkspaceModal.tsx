"use client";

import { useState } from "react";

import { deleteWorkspace } from "@/lib/api";
import type { Workspace } from "@/lib/types";

type Props = {
  workspaces: Workspace[];
  onClose: () => void;
  onRemoved: () => void;
};

export default function RemoveWorkspaceModal({
  workspaces,
  onClose,
  onRemoved,
}: Props) {
  const [wipeIndex, setWipeIndex] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Built-in workspaces can never be removed — silently skip if any
  // landed in the selection (the toolbar guards this too).
  const removable = workspaces.filter((w) => !w.is_builtin);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (removable.length === 0) {
      onClose();
      return;
    }
    setBusy(true);
    setErr(null);
    const failed: string[] = [];
    for (const w of removable) {
      try {
        await deleteWorkspace(w.id, { wipe_index: wipeIndex });
      } catch (e) {
        failed.push(
          `${w.label} — ${e instanceof Error ? e.message : String(e)}`,
        );
      }
    }
    setBusy(false);
    if (failed.length > 0) {
      setErr(failed.join("\n"));
      return;
    }
    onRemoved();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40"
      onClick={onClose}
    >
      <div
        className="w-[480px] max-w-[92vw] rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">
            워크스페이스 제거
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <p className="mb-3 text-xs text-slate-600">
          이 창에서{" "}
          <strong className="font-semibold">
            {removable.length}개 워크스페이스
          </strong>
          를 제거합니다. 등록된 폴더(원본 파일)는{" "}
          <span className="font-semibold text-slate-900">절대 삭제되지 않습니다</span>
          .
        </p>

        <ul className="mb-4 space-y-1 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
          {removable.map((w) => (
            <li key={w.id} className="flex items-center gap-2">
              <span className="font-medium text-slate-800">{w.label}</span>
              <span className="font-mono text-[10px] text-slate-500">
                {w.abs_path}
              </span>
            </li>
          ))}
        </ul>

        <form onSubmit={onSubmit} className="space-y-3">
          <label className="flex cursor-pointer items-start gap-2 rounded border border-slate-200 px-3 py-2 hover:bg-slate-50">
            <input
              type="checkbox"
              checked={wipeIndex}
              onChange={(e) => setWipeIndex(e.target.checked)}
              className="mt-0.5"
              disabled={busy}
            />
            <div>
              <div className="text-xs font-medium text-slate-800">
                인덱스도 함께 삭제
              </div>
              <p className="mt-0.5 text-[10px] text-slate-500">
                체크하지 않으면 vectorstore (
                <code className="rounded bg-white px-1">
                  data/vectorstore/&lt;slug&gt;/
                </code>
                ) 가 보존됩니다 — 같은 이름으로 다시 추가하면 인덱싱 없이 즉시 사용 가능. 체크하면 인덱스도 삭제 (재추가 시 재인덱싱 필요).
              </p>
            </div>
          </label>

          {err && (
            <div className="whitespace-pre-line rounded border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
              {err}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded border border-rose-700 bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-50"
            >
              {busy ? "제거 중..." : "제거"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
