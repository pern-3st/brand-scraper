export type Platform = "official_site" | "shopee";

export interface ProductRecord {
  // Mirrors backend/app/models.py::ProductRecord.
  // Core (populated by every scraper)
  product_name: string;
  product_url: string | null;
  image_url: string | null;
  price: number | null;
  mrp: number | null;
  currency: string;
  discount_pct: number | null;
  is_sold_out: boolean;
  scraped_at: string;

  // Shopee-only (null on official_site)
  item_id: number | null;
  rating_star: number | null;
  historical_sold_count: number | null;
  monthly_sold_count: number | null;
  monthly_sold_text: string | null;
  category_id: string | null;
  brand: string | null;
  liked_count: number | null;
  promotion_labels: string[];
  voucher_code: string | null;
  voucher_discount: number | null;

  // Official-site-only (null on shopee)
  category: string | null;
}

export interface ProductUpdate {
  // Mirrors backend/app/models.py::ProductUpdate.
  item_id: number;
  monthly_sold_count: number | null;
  monthly_sold_text: string | null;
  category_id: string | null;
  brand: string | null;
  liked_count: number | null;
  promotion_labels: string[] | null;
  voucher_code: string | null;
  voucher_discount: number | null;
}

export interface ScrapeStartResponse {
  scrape_id: string;
}

export interface DoneInfo {
  brand: string;
  count: number;
  file: string;
}

export interface LogEntry {
  message: string;
  level: "info" | "success" | "warning" | "error";
}

export interface Brand {
  id: string;
  name: string;
  created_at: string;
}

export interface RunAggregates {
  product_count: number;
  price_min: number | null;
  price_max: number | null;
  category_count: number | null;
}

export interface RunSummary {
  id: string;
  status: "ok" | "error" | "cancelled" | "in_progress" | string;
  aggregates: RunAggregates;
  created_at: string;
}

export interface BrandSummary {
  id: string;
  name: string;
  created_at: string;
  source_count: number;
  latest_run: RunSummary | null;
  latest_source_platform: string | null;
  latest_source_id: string | null;
}

export interface Source {
  id: string;
  brand_id: string;
  platform: Platform;
  name: string;
  spec: Record<string, unknown>;
  created_at: string;
}

export interface BrandDetail {
  id: string;
  name: string;
  created_at: string;
  sources: Source[];
  latest_run_by_source: Record<string, RunSummary | null>;
}

export interface Settings {
  openrouter_api_key_set: boolean;
  openrouter_api_key_hint: string;
  openrouter_model: string;
}

export interface ShopeeLoginStatus {
  open: boolean;
  profile_dir: string | null;
  opened_at: string | null;
  error: string | null;
}

// --- enrichment ------------------------------------------------------------
// Mirrors backend/app/models.py::FieldDef/FreeformPrompt/EnrichmentRequest/
// EnrichmentRow/UnifiedColumn/UnifiedTable.

export type FieldType = "str" | "int" | "float" | "bool" | "list[str]";

export interface FieldDef {
  id: string;
  label: string;
  type: FieldType;
  description: string;
  category: string | null;
}

export interface FreeformPrompt {
  id: string;
  label: string;
  prompt: string;
}

export interface EnrichmentRequest {
  curated_fields: string[];
  freeform_prompts: FreeformPrompt[];
}

export interface EnrichmentFieldsResponse {
  fields: FieldDef[];
  supports_freeform: boolean;
}

export interface EnrichmentStartResponse {
  session_id: string;
}

export interface EnrichmentSummary {
  id: string;
  status: "ok" | "cancelled" | "error" | "in_progress" | string;
  aggregates: Record<string, number | null>;
  request: {
    curated_fields?: string[];
    freeform_prompts?: FreeformPrompt[];
  };
}

export interface UnifiedColumn {
  id: string;
  label: string;
  type: FieldType | null;
  source: "scrape" | "enrichment";
  enrichment_id: string | null;
}

export type UnifiedRow = Record<string, unknown> & { product_key: string };

export interface UnifiedTable {
  columns: UnifiedColumn[];
  rows: UnifiedRow[];
}

export interface EnrichmentRowEvent {
  product_key: string;
  values: Record<string, unknown>;
  errors: Record<string, string>;
  index: number;
  total: number;
}

export interface SavedFreeformPrompt {
  id: string;
  label: string;
  prompt: string;
  last_used_at: string;
  use_count: number;
}

export interface EnrichmentHistory {
  most_recent: {
    curated_fields: string[];
    freeform_prompts: FreeformPrompt[];
  } | null;
  saved_prompts: SavedFreeformPrompt[];
}

export interface EnrichmentStartedEvent {
  enrichment_id: string;
  total_products: number;
  products_skipped_no_key: number;
  products_skipped_already_enriched?: number;
  requested_fields: string[];
}
