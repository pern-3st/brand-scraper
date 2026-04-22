"use client";

interface BrandInputProps {
  brandUrl: string;
  onBrandUrlChange: (value: string) => void;
}

export default function BrandInput({
  brandUrl,
  onBrandUrlChange,
}: BrandInputProps) {
  return (
    <div>
      <label
        htmlFor="brand-url"
        className="block text-sm font-medium text-foreground/70 mb-1.5"
      >
        Brand URL
      </label>
      <input
        id="brand-url"
        type="url"
        placeholder="https://www.next.co.uk"
        value={brandUrl}
        onChange={(e) => onBrandUrlChange(e.target.value)}
        className="w-full rounded-xl bg-white ring-1 ring-border px-4 py-2.5 text-sm placeholder:text-muted-fg focus:outline-none focus:ring-2 focus:ring-accent/40 transition-shadow"
      />
    </div>
  );
}
