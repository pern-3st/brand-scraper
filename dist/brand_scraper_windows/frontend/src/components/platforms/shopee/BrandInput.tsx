"use client";

import { useEffect, useState } from "react";

const MIN_PRODUCTS = 1;
const MAX_PRODUCTS = 1000;

interface ShopeeBrandInputProps {
  shopUrl: string;
  maxProducts: number;
  onShopUrlChange: (value: string) => void;
  onMaxProductsChange: (value: number) => void;
}

export default function ShopeeBrandInput({
  shopUrl,
  maxProducts,
  onShopUrlChange,
  onMaxProductsChange,
}: ShopeeBrandInputProps) {
  const [draft, setDraft] = useState(String(maxProducts));

  useEffect(() => {
    setDraft(String(maxProducts));
  }, [maxProducts]);

  return (
    <div className="space-y-4">
      <div>
        <label
          htmlFor="shopee-shop-url"
          className="block text-sm font-medium text-foreground/70 mb-1.5"
        >
          Shopee Shop URL
        </label>
        <input
          id="shopee-shop-url"
          type="url"
          placeholder="https://shopee.sg/levis_singapore"
          value={shopUrl}
          onChange={(e) => onShopUrlChange(e.target.value)}
          className="w-full rounded-xl bg-white ring-1 ring-border px-4 py-2.5 text-sm placeholder:text-muted-fg focus:outline-none focus:ring-2 focus:ring-accent/40 transition-shadow"
        />
        <p className="mt-1.5 text-xs text-muted-fg">
          Paste the full storefront URL, e.g. https://shopee.sg/levis_singapore
        </p>
      </div>
      <div>
        <label
          htmlFor="shopee-max-products"
          className="block text-sm font-medium text-foreground/70 mb-1.5"
        >
          Max products
        </label>
        <input
          id="shopee-max-products"
          type="number"
          inputMode="numeric"
          min={MIN_PRODUCTS}
          max={MAX_PRODUCTS}
          step={1}
          value={draft}
          onChange={(e) => {
            const text = e.target.value;
            setDraft(text);
            if (text === "") return;
            const parsed = Number(text);
            if (Number.isFinite(parsed) && parsed >= MIN_PRODUCTS) {
              onMaxProductsChange(
                Math.min(MAX_PRODUCTS, Math.floor(parsed)),
              );
            }
          }}
          onBlur={() => {
            const parsed = Number(draft);
            if (draft === "" || !Number.isFinite(parsed) || parsed < MIN_PRODUCTS) {
              setDraft(String(maxProducts));
            } else {
              const clamped = Math.min(MAX_PRODUCTS, Math.floor(parsed));
              setDraft(String(clamped));
              if (clamped !== maxProducts) onMaxProductsChange(clamped);
            }
          }}
          className="w-full rounded-xl bg-white ring-1 ring-border px-4 py-2.5 text-sm placeholder:text-muted-fg focus:outline-none focus:ring-2 focus:ring-accent/40 transition-shadow"
        />
      </div>
    </div>
  );
}
