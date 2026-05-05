"use client";

import { useEffect, useRef, useState } from "react";
import type { ColumnFiltersState, FilterFn } from "@tanstack/react-table";
import type { UnifiedColumn } from "@/types";
import type { TableRow } from "../SnapshotTable";

interface Props {
  columns: UnifiedColumn[];
  filters: ColumnFiltersState;
  setFilters: (updater: (prev: ColumnFiltersState) => ColumnFiltersState) => void;
}

export default function FilterChips({ columns, filters, setFilters }: Props) {
  const has = (id: string) => columns.some((c) => c.id === id);
  const get = (id: string) => filters.find((f) => f.id === id)?.value;
  // Chips MUST pass `undefined` to clear a filter; any defined value (including
  // `false` or `0`) is treated as an active filter so we don't silently drop it.
  const set = (id: string, value: unknown) =>
    setFilters((prev) => {
      const without = prev.filter((f) => f.id !== id);
      return value === undefined ? without : [...without, { id, value }];
    });

  const activeCount = filters.length;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {has("is_sold_out") && (
        <SoldOutChip value={get("is_sold_out") as SoldOutState} onChange={(v) => set("is_sold_out", v)} />
      )}
      {has("price") && (
        <RangeChip
          label="Price"
          value={get("price") as Range}
          onChange={(v) => set("price", v)}
        />
      )}
      {has("discount_pct") && (
        <ToggleChip
          label="Has discount"
          active={get("discount_pct") === true}
          onChange={(v) => set("discount_pct", v ? true : undefined)}
        />
      )}
      {has("rating_star") && (
        <MinSelectChip
          label="Rating"
          unit="★"
          options={[3, 4, 4.5]}
          value={get("rating_star") as number | undefined}
          onChange={(v) => set("rating_star", v)}
        />
      )}
      {has("monthly_sold_count") && (
        <MinNumberChip
          label="Monthly sold"
          value={get("monthly_sold_count") as number | undefined}
          onChange={(v) => set("monthly_sold_count", v)}
        />
      )}
      {activeCount > 0 && (
        <button
          type="button"
          onClick={() => setFilters(() => [])}
          className="text-xs text-foreground/50 hover:text-foreground/80 underline-offset-2 hover:underline"
        >
          Clear all
        </button>
      )}
    </div>
  );
}

// ---- chip primitives -----------------------------------------------------

type SoldOutState = "in_stock" | "sold_out" | undefined;
type Range = { min?: number; max?: number } | undefined;

function SoldOutChip({ value, onChange }: { value: SoldOutState; onChange: (v: SoldOutState) => void }) {
  return (
    <div className="inline-flex rounded-full ring-1 ring-border bg-muted/40 p-0.5 text-xs">
      <Seg label="All" active={value === undefined} onClick={() => onChange(undefined)} />
      <Seg label="In stock" active={value === "in_stock"} onClick={() => onChange("in_stock")} />
      <Seg label="Sold out" active={value === "sold_out"} onClick={() => onChange("sold_out")} />
    </div>
  );
}

function Seg({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-2.5 py-0.5 transition-colors ${
        active ? "bg-card text-foreground/90 shadow-sm" : "text-foreground/55 hover:text-foreground/80"
      }`}
    >
      {label}
    </button>
  );
}

function ToggleChip({ label, active, onChange }: { label: string; active: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!active)}
      className={`rounded-full px-2.5 py-1 text-xs ring-1 transition-colors ${
        active
          ? "bg-accent-soft text-accent ring-accent/30"
          : "bg-muted/40 text-foreground/60 ring-border hover:bg-muted/60"
      }`}
    >
      {label}
    </button>
  );
}

function Popover({
  label,
  active,
  summary,
  children,
}: {
  label: string;
  active: boolean;
  summary?: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`rounded-full px-2.5 py-1 text-xs ring-1 transition-colors inline-flex items-center gap-1 ${
          active
            ? "bg-accent-soft text-accent ring-accent/30"
            : "bg-muted/40 text-foreground/60 ring-border hover:bg-muted/60"
        }`}
      >
        {label}
        {summary && <span className="text-foreground/50">: {summary}</span>}
        <span className="text-[10px] opacity-60">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 z-20 min-w-44 rounded-xl bg-card ring-1 ring-border shadow-lg p-3">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function RangeChip({ label, value, onChange }: { label: string; value: Range; onChange: (v: Range) => void }) {
  const summary =
    value && (value.min !== undefined || value.max !== undefined)
      ? `${value.min ?? "*"}–${value.max ?? "*"}`
      : undefined;
  return (
    <Popover label={label} active={!!summary} summary={summary}>
      {() => (
        <div className="flex items-center gap-2">
          <NumberInput
            placeholder="min"
            value={value?.min}
            onChange={(min) => onChange(narrowRange({ ...value, min }))}
          />
          <span className="text-foreground/40">–</span>
          <NumberInput
            placeholder="max"
            value={value?.max}
            onChange={(max) => onChange(narrowRange({ ...value, max }))}
          />
        </div>
      )}
    </Popover>
  );
}

function narrowRange(r: { min?: number; max?: number }): Range {
  if (r.min === undefined && r.max === undefined) return undefined;
  return r;
}

function MinSelectChip({
  label,
  unit,
  options,
  value,
  onChange,
}: {
  label: string;
  unit?: string;
  options: number[];
  value: number | undefined;
  onChange: (v: number | undefined) => void;
}) {
  const summary = value !== undefined ? `${unit ?? ""}${value}+` : undefined;
  return (
    <Popover label={label} active={value !== undefined} summary={summary}>
      {(close) => (
        <div className="flex flex-col gap-1 min-w-32">
          <RowOption label="Any" active={value === undefined} onClick={() => { onChange(undefined); close(); }} />
          {options.map((o) => (
            <RowOption
              key={o}
              label={`${unit ? unit + " " : ""}${o}+`}
              active={value === o}
              onClick={() => { onChange(o); close(); }}
            />
          ))}
        </div>
      )}
    </Popover>
  );
}

function MinNumberChip({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
}) {
  const summary = value !== undefined ? `≥ ${value}` : undefined;
  return (
    <Popover label={label} active={value !== undefined} summary={summary}>
      {() => (
        <NumberInput placeholder="min" value={value} onChange={onChange} />
      )}
    </Popover>
  );
}

function RowOption({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left text-xs px-2 py-1 rounded-md transition-colors ${
        active ? "bg-accent-soft text-accent" : "hover:bg-muted/60 text-foreground/80"
      }`}
    >
      {label}
    </button>
  );
}

function NumberInput({
  value,
  onChange,
  placeholder,
}: {
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  placeholder?: string;
}) {
  return (
    <input
      type="number"
      inputMode="decimal"
      value={value ?? ""}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw === "") { onChange(undefined); return; }
        const n = Number(raw);
        onChange(Number.isFinite(n) ? n : undefined);
      }}
      placeholder={placeholder}
      className="w-20 rounded-md bg-muted/60 ring-1 ring-border px-2 py-1 text-xs text-foreground/90 placeholder:text-foreground/40 focus:outline-none focus:ring-accent/40"
    />
  );
}

// ---- filter functions exposed for SnapshotTable to register --------------

export const filterFns: Record<string, FilterFn<TableRow>> = {
  is_sold_out: (row, columnId, filterValue) => {
    if (filterValue === undefined) return true;
    const v = row.getValue(columnId);
    if (filterValue === "in_stock") return v === false || v == null;
    if (filterValue === "sold_out") return v === true;
    return true;
  },
  price: (row, columnId, filterValue) => {
    const r = filterValue as Range;
    if (!r) return true;
    const v = row.getValue(columnId);
    const n = typeof v === "number" ? v : Number(v);
    if (!Number.isFinite(n)) return false;
    if (r.min !== undefined && n < r.min) return false;
    if (r.max !== undefined && n > r.max) return false;
    return true;
  },
  discount_pct: (row, columnId, filterValue) => {
    if (filterValue !== true) return true;
    const v = row.getValue(columnId);
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) && n > 0;
  },
  rating_star: (row, columnId, filterValue) => {
    if (typeof filterValue !== "number") return true;
    const v = row.getValue(columnId);
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) && n >= filterValue;
  },
  monthly_sold_count: (row, columnId, filterValue) => {
    if (typeof filterValue !== "number") return true;
    const v = row.getValue(columnId);
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) && n >= filterValue;
  },
};
