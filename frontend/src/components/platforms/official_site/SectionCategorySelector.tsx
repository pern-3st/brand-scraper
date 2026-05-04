"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CATEGORIES } from "@/lib/categories";
import { useDismissedCategories } from "@/lib/useDismissedCategories";
import type { Source } from "@/types";

interface SectionCategorySelectorProps {
  brandId: string;
  section: string;
  selectedCategories: string[];
  maxProducts: number;
  skipMenuNavigation: boolean;
  sources: Source[];
  initialCategories: string[];
  onSectionChange: (section: string) => void;
  onCategoriesChange: (categories: string[]) => void;
  onMaxProductsChange: (max: number) => void;
  onSkipMenuNavigationChange: (value: boolean) => void;
}

const SECTIONS = ["mens", "womens", "kids"];
const MAX_MIN = 5;
const MAX_MAX = 500;
const MAX_STEP = 5;

function norm(s: string): string {
  return s.trim().toLowerCase();
}

function uniqueByNorm(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const v of values) {
    const k = norm(v);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    out.push(v);
  }
  return out;
}

export default function SectionCategorySelector({
  brandId,
  section,
  selectedCategories,
  maxProducts,
  skipMenuNavigation,
  sources,
  initialCategories,
  onSectionChange,
  onCategoriesChange,
  onMaxProductsChange,
  onSkipMenuNavigationChange,
}: SectionCategorySelectorProps) {
  const builtIn = useMemo(() => CATEGORIES[section] ?? [], [section]);
  const dismissed = useDismissedCategories(brandId);
  const dismissedForSection = dismissed.get(section);

  const [pendingCustom, setPendingCustom] = useState<string[]>([]);
  const [addingInput, setAddingInput] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (addingInput !== null) {
      inputRef.current?.focus();
    }
  }, [addingInput]);

  const builtInSet = useMemo(
    () => new Set(builtIn.map(norm)),
    [builtIn],
  );

  const usedCustom = useMemo(() => {
    const raw: string[] = [];
    for (const s of sources) {
      if (s.platform !== "official_site") continue;
      if (s.spec.section !== section) continue;
      const cats = s.spec.categories;
      if (!Array.isArray(cats)) continue;
      for (const c of cats) {
        if (typeof c !== "string") continue;
        if (builtInSet.has(norm(c))) continue;
        raw.push(c);
      }
    }
    return uniqueByNorm(raw);
  }, [sources, section, builtInSet]);

  const customChips = useMemo(() => {
    const dismissedSet = new Set(dismissedForSection.map(norm));
    const selectedSet = new Set(selectedCategories.map(norm));
    const initialSet = new Set(initialCategories.map(norm));
    const combined = uniqueByNorm([...usedCustom, ...pendingCustom]);
    return combined.filter((c) => {
      const n = norm(c);
      if (dismissedSet.has(n)) {
        // Keep chip visible if it's currently selected in this session
        // OR if we're editing a source that originally had it.
        return selectedSet.has(n) || initialSet.has(n);
      }
      return true;
    });
  }, [
    usedCustom,
    pendingCustom,
    dismissedForSection,
    selectedCategories,
    initialCategories,
  ]);

  const allChips = useMemo(
    () => [...builtIn, ...customChips],
    [builtIn, customChips],
  );

  function findChipByNorm(value: string): string | undefined {
    const n = norm(value);
    return allChips.find((c) => norm(c) === n);
  }

  function toggleCategory(cat: string) {
    const n = norm(cat);
    if (selectedCategories.some((c) => norm(c) === n)) {
      onCategoriesChange(selectedCategories.filter((c) => norm(c) !== n));
    } else {
      onCategoriesChange([...selectedCategories, cat]);
    }
  }

  function selectAll() {
    onCategoriesChange([...allChips]);
  }

  function selectNone() {
    onCategoriesChange([]);
  }

  function openAddInput() {
    setAddingInput("");
  }

  function closeAddInput() {
    setAddingInput(null);
  }

  function commitAddInput() {
    if (addingInput === null) return;
    const trimmed = addingInput.trim();
    if (!trimmed) {
      closeAddInput();
      return;
    }
    const n = norm(trimmed);

    const existingChip = findChipByNorm(trimmed);
    if (existingChip) {
      if (!selectedCategories.some((c) => norm(c) === n)) {
        onCategoriesChange([...selectedCategories, existingChip]);
      }
      closeAddInput();
      return;
    }

    // New custom. If it's in dismissed, un-dismiss.
    if (dismissedForSection.some((c) => norm(c) === n)) {
      dismissed.undismiss(section, trimmed);
    }

    setPendingCustom((prev) => {
      if (prev.some((c) => norm(c) === n)) return prev;
      return [...prev, trimmed];
    });
    onCategoriesChange([...selectedCategories, trimmed]);
    closeAddInput();
  }

  function removeCustom(cat: string) {
    const n = norm(cat);

    // Deselect if selected
    if (selectedCategories.some((c) => norm(c) === n)) {
      onCategoriesChange(selectedCategories.filter((c) => norm(c) !== n));
    }

    // If it's only in pendingCustom and not used by any existing source, drop it.
    const inPending = pendingCustom.some((c) => norm(c) === n);
    const inUsed = usedCustom.some((c) => norm(c) === n);

    if (inPending && !inUsed) {
      setPendingCustom((prev) => prev.filter((c) => norm(c) !== n));
      return;
    }

    // Otherwise dismiss persistently
    dismissed.dismiss(section, cat);
  }

  function changeSection(s: string) {
    if (s === section) return;
    onSectionChange(s);
    onCategoriesChange([]);
    setPendingCustom([]);
    closeAddInput();
  }

  return (
    <div className="space-y-6">
      {/* Section pills */}
      <div>
        <span className="block text-sm font-medium text-foreground/70 mb-2">
          Section
        </span>
        <div className="flex gap-2">
          {SECTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => changeSection(s)}
              className={`rounded-full px-5 py-2 text-sm font-medium transition-colors ${
                section === s
                  ? "bg-accent text-white"
                  : "bg-muted text-foreground/50 hover:bg-muted/80"
              }`}
            >
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Category chips */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-foreground/70">
            Categories
          </span>
          <div className="flex gap-3 text-xs">
            <button
              type="button"
              onClick={selectAll}
              className="text-accent hover:text-accent-hover transition-colors"
            >
              Select all
            </button>
            <button
              type="button"
              onClick={selectNone}
              className="text-accent hover:text-accent-hover transition-colors"
            >
              Clear
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {builtIn.map((cat) => {
            const selected = selectedCategories.some((c) => norm(c) === norm(cat));
            return (
              <button
                key={`builtin:${cat}`}
                type="button"
                onClick={() => toggleCategory(cat)}
                className={`rounded-full px-4 py-1.5 text-sm transition-colors ${
                  selected
                    ? "bg-accent-soft text-accent font-medium ring-1 ring-accent/30"
                    : "bg-muted text-foreground/50 hover:bg-muted/80"
                }`}
              >
                {selected && (
                  <span className="mr-1.5" aria-hidden>
                    &#10003;
                  </span>
                )}
                {cat}
              </button>
            );
          })}

          {customChips.map((cat) => {
            const selected = selectedCategories.some((c) => norm(c) === norm(cat));
            return (
              <span
                key={`custom:${norm(cat)}`}
                className={`group relative inline-flex items-center rounded-full pl-4 pr-2 py-1.5 text-sm transition-colors ${
                  selected
                    ? "bg-accent-soft text-accent font-medium ring-1 ring-accent/30"
                    : "bg-muted text-foreground/50 hover:bg-muted/80"
                }`}
              >
                <button
                  type="button"
                  onClick={() => toggleCategory(cat)}
                  className="flex items-center"
                >
                  {selected && (
                    <span className="mr-1.5" aria-hidden>
                      &#10003;
                    </span>
                  )}
                  {cat}
                </button>
                <button
                  type="button"
                  onClick={() => removeCustom(cat)}
                  aria-label={`Remove ${cat}`}
                  className="ml-1.5 text-foreground/40 hover:text-foreground/80 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                >
                  &times;
                </button>
              </span>
            );
          })}

          {addingInput === null ? (
            <button
              type="button"
              onClick={openAddInput}
              className="rounded-full px-3 py-1.5 text-sm text-foreground/50 bg-muted/50 ring-1 ring-dashed ring-border hover:bg-muted hover:text-foreground/70 transition-colors"
            >
              + Add category
            </button>
          ) : (
            <span className="inline-flex items-center rounded-full bg-muted ring-1 ring-border pl-3 pr-1 py-0.5">
              <input
                ref={inputRef}
                value={addingInput}
                onChange={(e) => setAddingInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitAddInput();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    closeAddInput();
                  }
                }}
                onBlur={() => {
                  if ((addingInput ?? "").trim() === "") {
                    closeAddInput();
                  }
                }}
                placeholder="category name"
                className="bg-transparent outline-none text-sm w-36"
              />
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={commitAddInput}
                aria-label="Add category"
                className="ml-1 rounded-full px-2 py-0.5 text-accent hover:bg-accent/10 text-sm"
              >
                &#10003;
              </button>
            </span>
          )}
        </div>
      </div>

      {/* Max products slider */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label
            htmlFor="max-products"
            className="text-sm font-medium text-foreground/70"
          >
            Max products per category
          </label>
          <span className="text-sm font-semibold text-purple-700 bg-purple-100 rounded-full px-3 py-0.5">
            {maxProducts}
          </span>
        </div>
        <input
          id="max-products"
          type="range"
          min={MAX_MIN}
          max={MAX_MAX}
          step={MAX_STEP}
          value={maxProducts}
          onChange={(e) => onMaxProductsChange(Number(e.target.value))}
          className="w-full accent-accent"
        />
        <div className="flex justify-between text-xs text-muted-fg mt-1">
          <span>{MAX_MIN}</span>
          <span>{MAX_MAX}</span>
        </div>
      </div>

      {/* Skip menu navigation toggle */}
      <div>
        <label className="flex items-start gap-3 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={skipMenuNavigation}
            onChange={(e) => onSkipMenuNavigationChange(e.target.checked)}
            className="mt-0.5 accent-accent"
          />
          <span>
            <span className="block font-medium text-foreground/70">
              Skip menu navigation
            </span>
            <span className="block text-xs text-muted-fg mt-0.5">
              Start directly from the URL instead of hunting the top nav.
              Use when the URL is already inside the target section.
            </span>
          </span>
        </label>
      </div>
    </div>
  );
}
