export interface AttributeDef {
  key: string;
  label: string;
  type: "text" | "number" | "boolean" | "select";
  required?: boolean;
  options?: string[];
  unit?: string;
  min?: number;
  max?: number;
}

export interface Category {
  id: string;
  name: string;
  description: string | null;
  attribute_schema: { attributes: AttributeDef[] };
  is_active: boolean;
}

export interface Brand {
  id: string;
  name: string;
  manufacturer: string | null;
  country_of_origin: string | null;
  is_active: boolean;
}

export interface Uom {
  id: string;
  code: string;
  name: string;
  category: string | null;
  decimal_scale: number;
  is_active: boolean;
}

export interface Variant {
  id: string;
  product_id: string;
  variant_code: string;
  variant_name: string;
  uom_id: string;
  attributes: Record<string, string | number | boolean>;
  is_active: boolean;
}

export interface Product {
  id: string;
  sku: string;
  name: string;
  category_id: string;
  brand_id: string | null;
  base_uom_id: string;
  description: string | null;
  tax_rate: string;
  lot_tracking_mode: "none" | "lot" | "lot_expiry";
  is_active: boolean;
  variants: Variant[];
}

export interface ProductListItem {
  id: string;
  sku: string;
  name: string;
  is_active: boolean;
  tax_rate: string;
  category_name: string;
  brand_name: string | null;
  base_uom_code: string;
  variant_count: number;
}

export interface SearchHit {
  product_id: string;
  variant_id: string | null;
  label: string;
  sku: string;
  variant_code: string | null;
  uom_code: string;
}
