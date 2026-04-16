"use client";

import { CATEGORIES } from "@/lib/categories";

interface SectionCategorySelectorProps {
  section: string;
  selectedCategories: string[];
  maxProducts: number;
  onSectionChange: (section: string) => void;
  onCategoriesChange: (categories: string[]) => void;
  onMaxProductsChange: (max: number) => void;
}

const SECTIONS = ["mens", "womens", "kids"];
const MAX_MIN = 5;
const MAX_MAX = 50;
const MAX_STEP = 5;


export default function SectionCategorySelector({
  section,
  selectedCategories,
  maxProducts,
  onSectionChange,
  onCategoriesChange,
  onMaxProductsChange,
}: SectionCategorySelectorProps) {
  const categories = CATEGORIES[section] ?? [];

  function toggleCategory(cat: string) {
    if (selectedCategories.includes(cat)) {
      onCategoriesChange(selectedCategories.filter((c) => c !== cat));
    } else {
      onCategoriesChange([...selectedCategories, cat]);
    }
  }

  function selectAll() {
    onCategoriesChange([...categories]);
  }

  function selectNone() {
    onCategoriesChange([]);
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
              onClick={() => {
                onSectionChange(s);
                onCategoriesChange([]);
              }}
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
          {categories.map((cat) => {
            const selected = selectedCategories.includes(cat);
            return (
              <button
                key={cat}
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
    </div>
  );
}
