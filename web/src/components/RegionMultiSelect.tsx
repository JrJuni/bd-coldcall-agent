"use client";

import { useEffect, useMemo, useState } from "react";

import { getDiscoveryRegions } from "@/lib/api";
import type { RegionGroup } from "@/lib/types";

type Props = {
  /** Selected ISO alpha-2 country codes (lowercase). Empty = "any". */
  value: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
};

/**
 * Phase 12 — country-level multi-select for the Discovery form.
 *
 * Renders one expandable section per continent group (`<details>`-style
 * disclosure) with a per-group "select all" toggle and a per-country
 * checkbox. The header shows the selection summary so the form's vertical
 * footprint stays small in the common "any" / "1-2 countries" cases.
 */
export default function RegionMultiSelect({ value, onChange, disabled }: Props) {
  const [groups, setGroups] = useState<RegionGroup[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDiscoveryRegions()
      .then((cfg) => {
        setGroups(cfg.groups);
        // Auto-expand the first group on cold load so a fresh user can see
        // there's a checklist to interact with.
        if (cfg.groups.length > 0) {
          setExpanded({ [cfg.groups[0].id]: true });
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const selected = useMemo(() => new Set(value), [value]);

  const summaryLabel = useMemo(() => {
    if (selected.size === 0) return "Any region";
    const labels: string[] = [];
    for (const g of groups) {
      for (const c of g.countries) {
        if (selected.has(c.code)) labels.push(c.label);
      }
    }
    if (labels.length === 0) return `${selected.size} selected`;
    if (labels.length <= 3) return labels.join(", ");
    return `${labels.slice(0, 3).join(", ")} +${labels.length - 3}`;
  }, [selected, groups]);

  function toggleCountry(code: string) {
    if (disabled) return;
    const next = new Set(value);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    onChange(Array.from(next));
  }

  function toggleGroup(group: RegionGroup) {
    if (disabled) return;
    const codes = group.countries.map((c) => c.code);
    const allSelected = codes.every((c) => selected.has(c));
    const next = new Set(value);
    if (allSelected) {
      codes.forEach((c) => next.delete(c));
    } else {
      codes.forEach((c) => next.add(c));
    }
    onChange(Array.from(next));
  }

  function clearAll() {
    if (disabled) return;
    onChange([]);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-700">{summaryLabel}</span>
        {selected.size > 0 && (
          <button
            type="button"
            onClick={clearAll}
            disabled={disabled}
            className="text-xs text-slate-500 hover:text-slate-700 hover:underline disabled:opacity-50"
          >
            Clear ({selected.size})
          </button>
        )}
      </div>

      {error && <p className="text-xs text-red-600">regions.yaml load failed: {error}</p>}

      <div className="rounded-md border border-slate-200 bg-white">
        {groups.length === 0 && !error && (
          <p className="px-3 py-2 text-xs text-slate-500">Loading regions…</p>
        )}
        {groups.map((g) => {
          const codes = g.countries.map((c) => c.code);
          const allSelected = codes.every((c) => selected.has(c)) && codes.length > 0;
          const someSelected = codes.some((c) => selected.has(c));
          const isOpen = !!expanded[g.id];
          return (
            <div key={g.id} className="border-b border-slate-100 last:border-b-0">
              <div className="flex items-center gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() => setExpanded((prev) => ({ ...prev, [g.id]: !prev[g.id] }))}
                  className="text-slate-500 hover:text-slate-800"
                  aria-label={isOpen ? `Collapse ${g.label}` : `Expand ${g.label}`}
                >
                  {isOpen ? "▾" : "▸"}
                </button>
                <button
                  type="button"
                  onClick={() => toggleGroup(g)}
                  disabled={disabled}
                  className="flex-1 text-left text-sm font-medium text-slate-800 hover:underline disabled:opacity-50"
                >
                  {g.label}
                </button>
                <span className="text-xs text-slate-500">
                  {codes.filter((c) => selected.has(c)).length}/{codes.length}
                </span>
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = !allSelected && someSelected;
                  }}
                  onChange={() => toggleGroup(g)}
                  disabled={disabled}
                  aria-label={`Select all ${g.label}`}
                />
              </div>
              {isOpen && (
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 bg-slate-50 px-7 py-2 sm:grid-cols-3">
                  {g.countries.map((c) => (
                    <label
                      key={c.code}
                      className="flex items-center gap-2 text-xs text-slate-700"
                    >
                      <input
                        type="checkbox"
                        checked={selected.has(c.code)}
                        onChange={() => toggleCountry(c.code)}
                        disabled={disabled}
                      />
                      <span>
                        {c.label}{" "}
                        <span className="text-slate-400">({c.code})</span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
