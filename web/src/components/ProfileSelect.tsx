"use client";

import { useEffect, useMemo, useState } from "react";

import { getDiscoveryProfiles } from "@/lib/api";
import type { DiscoveryProfile } from "@/lib/types";

type Props = {
  value: string;
  onChange: (next: string, profile: DiscoveryProfile | undefined) => void;
  disabled?: boolean;
};

/**
 * Phase 12 follow-up (B5) — yaml-driven scoring profile dropdown for the
 * Discovery form (was `ProductSelect`).
 *
 * Profiles come from `GET /discovery/profiles` (sourced from
 * `config/weights.yaml::profiles`). The list always starts with an
 * implicit `default` entry so a fresh user with no named profiles still
 * sees a sensible base option.
 *
 * The selected profile's `description` renders below the dropdown so the
 * user understands the weight bias before running. The full `profile`
 * object (incl. `effective_weights`) is passed to `onChange` so the
 * caller can seed the run-form weights editor without a second fetch.
 */
export default function ProfileSelect({ value, onChange, disabled }: Props) {
  const [profiles, setProfiles] = useState<DiscoveryProfile[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDiscoveryProfiles()
      .then((r) => {
        setProfiles(r.profiles);
        // If the current value isn't in the freshly-loaded list (e.g. the
        // user removed `databricks` from weights.yaml between sessions),
        // fall back to the first option so the form stays valid.
        if (
          r.profiles.length > 0 &&
          !r.profiles.find((p) => p.key === value)
        ) {
          const first = r.profiles[0];
          onChange(first.key, first);
        } else {
          const match = r.profiles.find((p) => p.key === value);
          if (match) onChange(value, match);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = useMemo(
    () => profiles.find((p) => p.key === value),
    [profiles, value],
  );

  return (
    <div className="space-y-1">
      <select
        value={value}
        onChange={(e) => {
          const next = e.target.value;
          onChange(next, profiles.find((p) => p.key === next));
        }}
        disabled={disabled || profiles.length === 0}
        className="block w-full rounded-md border border-slate-300 px-3 py-2 disabled:bg-slate-50"
      >
        {profiles.length === 0 ? (
          <option value={value}>{value || "default"}</option>
        ) : (
          profiles.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
              {p.is_default ? " (기본 프로파일)" : ""}
            </option>
          ))
        )}
      </select>
      {error && (
        <p className="text-xs text-red-600">
          weights.yaml load failed: {error}
        </p>
      )}
      {current?.description && (
        <p className="text-xs text-slate-500">{current.description}</p>
      )}
    </div>
  );
}
