"use client";

import { useState } from "react";

import { createWorkspace } from "@/lib/api";
import type { Workspace } from "@/lib/types";

type Props = {
  onClose: () => void;
  onCreated: (ws: Workspace) => void;
};

export default function AddWorkspaceModal({ onClose, onCreated }: Props) {
  const [label, setLabel] = useState("");
  const [absPath, setAbsPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!label.trim() || !absPath.trim()) {
      setErr("이름과 경로 모두 입력하세요.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const ws = await createWorkspace({
        label: label.trim(),
        abs_path: absPath.trim(),
      });
      onCreated(ws);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
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
            워크스페이스 추가
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

        <p className="mb-4 text-xs text-slate-500">
          PC 안의 임의 폴더를 RAG 워크스페이스로 등록합니다. 등록 후 해당
          폴더의 문서를 인덱싱·검색·discovery 에 사용할 수 있습니다.
        </p>

        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-700">
              이름
            </label>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="예: 개인 메모"
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-sky-500 focus:outline-none"
              disabled={busy}
              autoFocus
            />
            <p className="mt-1 text-[10px] text-slate-400">
              사이드바·breadcrumb 에 표시될 라벨. slug 는 자동 생성됩니다.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-700">
              절대 경로
            </label>
            <input
              type="text"
              value={absPath}
              onChange={(e) => setAbsPath(e.target.value)}
              placeholder="예: D:\\my-docs  또는  C:\\Users\\me\\Documents\\proj"
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 font-mono text-xs focus:border-sky-500 focus:outline-none"
              disabled={busy}
            />
            <p className="mt-1 text-[10px] text-slate-400">
              Windows 탐색기에서 폴더 우클릭 → &quot;경로로 복사&quot; 로
              붙여넣을 수 있습니다. 프로젝트의 <code>data/</code> 안 경로는
              거부됩니다.
            </p>
          </div>

          {err && (
            <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
              {err}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {busy ? "등록 중..." : "추가"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
