"use client";

import { useEffect, useRef, useState } from "react";

import { getActiveModel, setActiveModel } from "@/lib/api";
import type { ActiveModelView, AvailableModel } from "@/lib/types";

function shortModel(id: string): string {
  return id.replace(/^claude-/, "");
}

function rateLine(m: AvailableModel): string {
  return (
    `in $${m.input_per_mtok}/Mtok · ` +
    `out $${m.output_per_mtok}/Mtok · ` +
    `cache $${m.cache_read_per_mtok}/${m.cache_write_per_mtok}`
  );
}

export default function ActiveModelSelector({
  onChanged,
}: {
  onChanged?: () => void;
}) {
  const [view, setView] = useState<ActiveModelView | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);

  async function load() {
    try {
      setView(await getActiveModel());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  // Close popover on outside click
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!open) return;
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  async function pick(modelId: string) {
    if (!view || modelId === view.active || busy) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const next = await setActiveModel(modelId);
      setView(next);
      setMsg(`활성 모델 → ${shortModel(modelId)}`);
      setOpen(false);
      onChanged?.();
      setTimeout(() => setMsg(null), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!view) {
    return (
      <div className="rounded border border-slate-200 px-3 py-1.5 text-xs text-slate-400">
        활성 모델 불러오는 중...
      </div>
    );
  }

  const activeRates = view.available.find((m) => m.id === view.active);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={busy}
        className="flex items-center gap-2 rounded border border-slate-300 bg-white px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50"
        title={
          activeRates
            ? `${view.active}\n${rateLine(activeRates)}`
            : view.active ?? "no active model"
        }
      >
        <span className="text-[10px] uppercase tracking-wide text-slate-500">
          활성 모델
        </span>
        <span className="font-mono text-slate-900">
          {view.active ? shortModel(view.active) : "—"}
        </span>
        <span className="text-slate-400" aria-hidden>
          ▾
        </span>
      </button>

      {open && (
        <div className="absolute right-0 z-10 mt-1 w-80 rounded-md border border-slate-200 bg-white shadow-lg">
          {view.available.length === 0 ? (
            <p className="p-3 text-xs text-amber-700">
              pricing.yaml 에 등록된 모델이 없습니다. Cost 페이지 하단 "단가 &
              예산" 에서 모델을 추가하세요.
            </p>
          ) : (
            <ul className="max-h-72 overflow-auto py-1 text-xs">
              {view.available.map((m) => {
                const isActive = m.id === view.active;
                return (
                  <li key={m.id}>
                    <button
                      type="button"
                      onClick={() => pick(m.id)}
                      disabled={busy || isActive}
                      className={
                        "block w-full px-3 py-2 text-left transition " +
                        (isActive
                          ? "bg-slate-100 cursor-default"
                          : "hover:bg-slate-50")
                      }
                    >
                      <div className="flex items-center justify-between">
                        <code className="font-mono text-[11px] text-slate-900">
                          {m.id}
                        </code>
                        {isActive && (
                          <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-800">
                            활성
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 font-mono text-[10px] text-slate-500">
                        {rateLine(m)}
                      </p>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="border-t border-slate-100 p-2 text-[10px] text-slate-400">
            settings.yaml 의 llm.claude_model 을 갱신합니다. 변경 후 새로
            실행되는 run 부터 적용 (기존 run 의 단가는 그대로).
          </div>
        </div>
      )}

      {msg && (
        <p className="absolute right-0 mt-1 text-[10px] text-emerald-700">
          {msg}
        </p>
      )}
      {error && (
        <p className="absolute right-0 mt-1 max-w-xs text-[10px] text-rose-600">
          {error}
        </p>
      )}
    </div>
  );
}
