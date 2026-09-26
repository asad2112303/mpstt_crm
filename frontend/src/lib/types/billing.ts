/** Direct billing — Quick Bill and Sell from Stock. */

export type BillingMode = "quick" | "stock";

/** One row of the billing product picker. */
export interface BillingProduct {
  product_variant_id: string;
  product_id: string;
  sku: string;
  variant_code: string;
  label: string;
  product_name: string;
  variant_name: string;
  category: string | null;
  attributes: Record<string, string | number | boolean>;
  uom_code: string | null;
  tax_rate: string;
  track_stock: boolean;
  /** null for untracked products — they have no stock figure at all. */
  available: string | null;
  on_hand: string | null;
  suggested_price: string;
  has_cost: boolean;
  /** Present on the Products & Inventory views; omitted by the billing picker. */
  avg_cost?: string | null;
  standard_cost?: string | null;
  default_purchase_cost?: string | null;
  reorder_level?: string | null;
  low_stock?: boolean;
  created_via?: "catalogue" | "quick_bill" | "import";
}

/** One option step the picker asks about, e.g. Colour then Size. */
export interface CatalogueStep {
  key: string;
  label: string;
  unit?: string | null;
}

export interface CatalogueVariant {
  product_variant_id: string;
  variant_name: string;
  attributes: Record<string, string>;
  uom_code: string | null;
  track_stock: boolean;
  available: string | null;
  suggested_price: string;
  has_cost: boolean;
}

/** A product plus everything needed to narrow it down to one variant. */
export interface CatalogueProduct {
  product_id: string;
  name: string;
  sku: string;
  category: string | null;
  track_stock: boolean;
  tax_rate: string;
  steps: CatalogueStep[];
  variants: CatalogueVariant[];
}

/** Walk the steps, auto-applying any that have only one option left. */
export function narrow(
  product: CatalogueProduct,
  chosen: Record<string, string>,
): {
  candidates: CatalogueVariant[];
  applied: Record<string, string>;
  step: CatalogueStep | null;
  options: string[];
  variant: CatalogueVariant | null;
} {
  const applied: Record<string, string> = {};
  let candidates = product.variants;

  for (const step of product.steps) {
    const values = Array.from(
      new Set(candidates.map((v) => v.attributes[step.key]).filter(Boolean)),
    );
    const picked = chosen[step.key];
    if (picked && values.includes(picked)) {
      applied[step.key] = picked;
      candidates = candidates.filter((v) => v.attributes[step.key] === picked);
      continue;
    }
    // Only one value survives earlier choices, so it is not a question.
    if (values.length === 1) {
      applied[step.key] = values[0];
      candidates = candidates.filter((v) => v.attributes[step.key] === values[0]);
      continue;
    }
    if (values.length > 1) {
      return { candidates, applied, step, options: values, variant: null };
    }
  }
  return {
    candidates,
    applied,
    step: null,
    options: [],
    variant: candidates.length === 1 ? candidates[0] : null,
  };
}

export interface BillingCustomer {
  id: string;
  name: string;
  org_code: string;
  city: string | null;
  phone: string | null;
  lifecycle_status: string;
}

export interface QuickProductPayload {
  name: string;
  uom_code: string;
  category_id?: string | null;
  colour?: string | null;
  size?: string | null;
  sale_price?: string | null;
  purchase_cost?: string | null;
  tax_rate?: string;
  track_stock?: boolean;
  opening_quantity?: string | null;
}

/** A line as the user is editing it, before it becomes an invoice item. */
export interface DraftLine {
  key: string;
  /** Set once a catalogue product is chosen. */
  product?: BillingProduct;
  /** Free text typed before a product is chosen or created. */
  typedName: string;
  description: string;
  uom_code: string;
  quantity: string;
  unit_price: string;
  discount_percent: string;
  tax_rate: string;
  unit_cost: string;
  /** New products created inline carry their setup until the invoice saves. */
  newProduct?: QuickProductPayload;
}

export type CostSource =
  | "weighted_average"
  | "manual"
  | "product_default"
  | "missing";

export interface InvoiceProfit {
  cogs: string | null;
  gross_profit: string | null;
  cost_complete: boolean | null;
  sales_with_cost: string;
  sales_missing_cost: string;
  cost_coverage_percent?: string | null;
}

export interface InvoiceItem {
  id: string;
  product_id: string;
  product_variant_id: string;
  description_snapshot: string;
  specification_snapshot: Record<string, string | number | boolean>;
  quantity: string;
  uom_code: string;
  unit_price: string;
  discount_percent: string;
  tax_rate: string;
  line_net: string;
  line_tax: string;
  line_total: string;
  sort_order: number;
  line_source: "stock" | "quick_bill";
  cost_source: CostSource | null;
}

export interface Invoice {
  id: string;
  invoice_number: string | null;
  organization_id: string;
  invoice_date: string | null;
  due_date: string | null;
  payment_terms_days: number;
  status: "draft" | "issued" | "cancelled";
  derived_status: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  grand_total: string;
  allocated: string;
  outstanding: string;
  notes: string | null;
  is_direct: boolean;
  is_walk_in: boolean;
  walk_in_name: string | null;
  warehouse_id: string | null;
  reference_number: string | null;
  contact_person: string | null;
  contact_phone: string | null;
  billing_address: string | null;
  delivery_address: string | null;
  payment_terms_note: string | null;
  overall_discount_type: "percent" | "amount" | null;
  overall_discount_value: string;
  overall_discount_amount: string;
  delivery_charge: string;
  items: InvoiceItem[];
  profit: InvoiceProfit;
  stock?: { stock_moved: boolean; lines_stocked?: number; already_committed?: boolean };
}

export interface BusinessDashboard {
  range: { preset: string; from: string; to: string };
  sales: {
    net_sales: string;
    invoiced_total: string;
    delivery_charged: string;
    invoice_count: number;
    average_invoice_value: string;
    from_stock: string;
    quick_bill: string;
  };
  profit: {
    cogs: string;
    gross_profit: string;
    gross_margin_percent: string | null;
    sales_with_cost: string;
    sales_missing_cost: string;
    cost_coverage_percent: string | null;
    cost_complete: boolean;
  };
  cash: {
    collected: string;
    outstanding: string;
    overdue: string;
    open_invoices: number;
  };
  inventory: {
    value: string;
    uncosted_lines: number;
    low_stock_count: number;
  };
}

export interface BusinessBreakdown {
  range: { preset: string; from: string; to: string };
  bucket: "day" | "month";
  trend: { bucket: string; net_sales: string; gross_profit: string }[];
  top_products: {
    product_id: string; name: string; net_sales: string;
    quantity: string; gross_profit: string;
  }[];
  top_categories: { name: string; net_sales: string }[];
  top_customers: {
    organization_id: string; name: string; net_sales: string; invoice_count: number;
  }[];
  recent_invoices: {
    id: string; invoice_number: string | null; invoice_date: string | null;
    customer_name: string; grand_total: string; outstanding: string;
    payment_status: "paid" | "partially_paid" | "overdue" | "unpaid";
    is_direct: boolean;
  }[];
}

export const DATE_PRESETS = [
  { value: "today", label: "Today" },
  { value: "week", label: "This week" },
  { value: "month", label: "This month" },
  { value: "year", label: "This year" },
  { value: "custom", label: "Custom" },
] as const;

/** Money formatting for PKR, used across the billing screens. */
export function pkr(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-PK", {
    style: "currency",
    currency: "PKR",
    maximumFractionDigits: 0,
  });
}

export function pkrExact(value: string | number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-PK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Line maths mirrored from the server so the screen totals live. */
export function lineAmounts(line: {
  quantity: string; unit_price: string; discount_percent: string; tax_rate: string;
}) {
  const qty = Number(line.quantity || 0);
  const price = Number(line.unit_price || 0);
  const gross = qty * price;
  const discount = (gross * Number(line.discount_percent || 0)) / 100;
  const net = gross - discount;
  const tax = (net * Number(line.tax_rate || 0)) / 100;
  return { gross, discount, net, tax, total: net + tax };
}
