"use client";

import { useState } from "react";
import ShopeeBrandInput from "./BrandInput";

export default function AddSourceForm({
  onSubmit,
  onPrimaryUrlChange,
  initialSpec,
  submitLabel = "Add source",
}: {
  onSubmit: (spec: Record<string, unknown>) => void;
  onPrimaryUrlChange?: (url: string) => void;
  initialSpec?: Record<string, unknown>;
  submitLabel?: string;
}) {
  const [shopUrl, setShopUrl] = useState(
    typeof initialSpec?.shop_url === "string" ? initialSpec.shop_url : "",
  );
  const [maxProducts, setMaxProducts] = useState(
    typeof initialSpec?.max_products === "number" ? initialSpec.max_products : 1000,
  );
  const canSubmit = shopUrl.trim() !== "";
  return (
    <div className="space-y-4">
      <ShopeeBrandInput
        shopUrl={shopUrl}
        maxProducts={maxProducts}
        onShopUrlChange={(v) => {
          setShopUrl(v);
          onPrimaryUrlChange?.(v);
        }}
        onMaxProductsChange={setMaxProducts}
      />
      <button
        disabled={!canSubmit}
        onClick={() =>
          onSubmit({ shop_url: shopUrl, max_products: maxProducts })
        }
        className="w-full rounded-xl bg-accent px-4 py-2 text-sm text-white hover:bg-accent-hover disabled:opacity-40"
      >
        {submitLabel}
      </button>
    </div>
  );
}
