"use client";

import { useEffect, useMemo, useState } from "react";

import { getDiscoveryProducts } from "@/lib/api";
import type { DiscoveryProduct } from "@/lib/types";

type Props = {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
};

/**
 * Phase 12 — yaml-driven product dropdown for the Discovery form.
 *
 * Replaces the pre-Phase-12 free-text input. Products come from
 * `GET /discovery/products` (sourced from `config/weights.yaml::products`).
 * The list always starts with an implicit `default` entry so a fresh user
 * with no product profiles still sees a sensible base option.
 *
 * The currently-selected product's `description` renders below the
 * dropdown so the user understands the weight bias before running.
 */
export default function ProductSelect({ value, onChange, disabled }: Props) {
  const [products, setProducts] = useState<DiscoveryProduct[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDiscoveryProducts()
      .then((r) => {
        setProducts(r.products);
        // If the current value isn't in the freshly-loaded list (e.g. the
        // user removed `databricks` from weights.yaml between sessions),
        // fall back to the first option so the form stays valid.
        if (
          r.products.length > 0 &&
          !r.products.find((p) => p.key === value)
        ) {
          onChange(r.products[0].key);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = useMemo(
    () => products.find((p) => p.key === value),
    [products, value],
  );

  return (
    <div className="space-y-1">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || products.length === 0}
        className="block w-full rounded-md border border-slate-300 px-3 py-2 disabled:bg-slate-50"
      >
        {products.length === 0 ? (
          <option value={value}>{value || "default"}</option>
        ) : (
          products.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
              {p.is_default ? " (no product override)" : ""}
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
