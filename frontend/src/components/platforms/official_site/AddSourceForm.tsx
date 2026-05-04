"use client";

import { useState } from "react";
import BrandInput from "./BrandInput";
import SectionCategorySelector from "./SectionCategorySelector";

export default function AddSourceForm({
  onSubmit,
  initialSpec,
  submitLabel = "Add source",
}: {
  onSubmit: (spec: Record<string, unknown>) => void;
  initialSpec?: Record<string, unknown>;
  submitLabel?: string;
}) {
  const [brandUrl, setBrandUrl] = useState(
    typeof initialSpec?.brand_url === "string" ? initialSpec.brand_url : "",
  );
  const [section, setSection] = useState(
    typeof initialSpec?.section === "string" ? initialSpec.section : "mens",
  );
  const [categories, setCategories] = useState<string[]>(
    Array.isArray(initialSpec?.categories)
      ? (initialSpec!.categories as unknown[]).filter(
          (c): c is string => typeof c === "string",
        )
      : [],
  );
  const [maxProducts, setMaxProducts] = useState(
    typeof initialSpec?.max_products === "number" ? initialSpec.max_products : 10,
  );
  const [skipMenuNavigation, setSkipMenuNavigation] = useState(
    typeof initialSpec?.skip_menu_navigation === "boolean"
      ? initialSpec.skip_menu_navigation
      : false,
  );

  const canSubmit = brandUrl.trim() !== "" && categories.length > 0;

  return (
    <div className="space-y-4">
      <BrandInput
        brandUrl={brandUrl}
        onBrandUrlChange={setBrandUrl}
      />
      <SectionCategorySelector
        section={section}
        selectedCategories={categories}
        maxProducts={maxProducts}
        skipMenuNavigation={skipMenuNavigation}
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
