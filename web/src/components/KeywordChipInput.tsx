"use client";

import { useState, type KeyboardEvent } from "react";

type Props = {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
};

/**
 * Phase 12 — chip-style multi-keyword input for Discovery seed queries.
 *
 * Behavior:
 *   - Enter or comma adds the trimmed buffer as a chip.
 *   - Backspace on an empty buffer removes the trailing chip.
 *   - Click "×" on a chip removes it.
 *   - Duplicates (case-insensitive) are silently dropped — same dedup
 *     rule as the backend's `_normalize_seed_queries`.
 *   - Blur also commits a non-empty buffer so users who tab away keep
 *     their typing instead of losing it.
 *
 * Native input + state list — no external deps.
 */
export default function KeywordChipInput({
  value,
  onChange,
  placeholder,
  disabled,
}: Props) {
  const [draft, setDraft] = useState<string>("");

  function addChip(raw: string) {
    if (disabled) return;
    const trimmed = raw.trim();
    if (!trimmed) return;
    const lower = trimmed.toLowerCase();
    if (value.some((v) => v.toLowerCase() === lower)) {
      setDraft("");
      return;
    }
    onChange([...value, trimmed]);
    setDraft("");
  }

  function removeChip(idx: number) {
    if (disabled) return;
    const next = [...value];
    next.splice(idx, 1);
    onChange(next);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (disabled) return;
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addChip(draft);
      return;
    }
    if (e.key === "Backspace" && draft === "" && value.length > 0) {
      e.preventDefault();
      removeChip(value.length - 1);
    }
  }

  return (
    <div
      className={
        "flex flex-wrap items-center gap-2 rounded-md border border-slate-300 px-2 py-1.5" +
        (disabled ? " bg-slate-50 opacity-70" : " bg-white")
      }
    >
      {value.map((chip, idx) => (
        <span
          key={`${chip}-${idx}`}
          className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700"
        >
          <span>{chip}</span>
          <button
            type="button"
            onClick={() => removeChip(idx)}
            disabled={disabled}
            className="text-slate-500 hover:text-rose-600 disabled:opacity-50"
            aria-label={`Remove ${chip}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => addChip(draft)}
        placeholder={value.length === 0 ? placeholder : ""}
        disabled={disabled}
        className="min-w-[10ch] flex-1 border-none bg-transparent px-1 py-0.5 text-sm focus:outline-none disabled:opacity-50"
      />
    </div>
  );
}
