"use client";

import { useState } from "react";
import BrandInput from "./BrandInput";
import SectionCategorySelector from "./SectionCategorySelector";
import type { Source } from "@/types";

export default function AddSourceForm({
  brandId,
  sources,
  onSubmit,
  onPrimaryUrlChange,
  initialSpec,
  submitLabel = "Add source",
}: {
  brandId: string;
  sources: Source[];
  onSubmit: (spec: Record<string, unknown>) => void;
  onPrimaryUrlChange?: (url: string) => void;
  initialSpec?: Record<string, unknown>;
  submitLabel?: string;
}) {
  const [brandUrl, setBrandUrl] = useState(
    typeof initialSpec?.brand_url === "string" ? initialSpec.brand_url : "",
  );
  const initialSection =
    typeof initialSpec?.section === "string" ? initialSpec.section : "mens";
  const [section, setSection] = useState(initialSection);
  const initialCategoriesForSection: string[] = Array.isArray(
    initialSpec?.categories,
  )
    ? (initialSpec!.categories as unknown[]).filter(
        (c): c is string => typeof c === "string",
      )
    : [];
  const [categories, setCategories] = useState<string[]>(
    initialCategoriesForSection,
  );
  const [maxProducts, setMaxProducts] = useState(
    typeof initialSpec?.max_products === "number" ? initialSpec.max_products : 500,
  );
  const [skipMenuNavigation, setSkipMenuNavigation] = useState(
    typeof initialSpec?.skip_menu_navigation === "boolean"
      ? initialSpec.skip_menu_navigation
      : false,
  );

  const canSubmit = brandUrl.trim() !== "" && categories.length > 0;

  // Only surface initialCategories to the selector while the user is still on
  // the original section of the edited source — switching sections clears the
  // selection anyway, so the union is no longer meaningful.
  const initialCategoriesForSelector =
    initialSpec && section === initialSection ? initialCategoriesForSection : [];

  return (
    <div className="space-y-4">
      <BrandInput
        brandUrl={brandUrl}
        onBrandUrlChange={(v) => {
          setBrandUrl(v);
          onPrimaryUrlChange?.(v);
        }}
      />
      <SectionCategorySelector
        brandId={brandId}
        section={section}
        selectedCategories={categories}
        maxProducts={maxProducts}
        skipMenuNavigation={skipMenuNavigation}
        sources={sources}
        initialCategories={initialCategoriesForSelector}
        onSectionChange={setSection}
        onCategoriesChange={setCategories}
        onMaxProductsChange={setMaxProducts}
        onSkipMenuNavigationChange={setSkipMenuNavigation}
      />
      <button
        disabled={!canSubmit}
        onClick={() =>
          onSubmit({
            brand_url: brandUrl,
            section,
            categories,
            max_products: maxProducts,
            skip_menu_navigation: skipMenuNavigation,
          })
        }
        className="w-full rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover disabled:opacity-40"
      >
        {submitLabel}
      </button>
    </div>
  );
}
