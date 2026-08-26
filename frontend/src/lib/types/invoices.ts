export interface InvoiceItem {
  id: string;
  sales_order_item_id: string | null;
  product_id: string;
  product_variant_id: string;
  description_snapshot: string;
  specification_snapshot: Record<string, unknown>;
  quantity: string;
  uom_code: string;
  unit_price: string;
  discount_percent: string;
  tax_rate: string;
  line_net: string;
  line_tax: string;
  line_total: string;
  sort_order: number;
}

export type InvoiceDerivedStatus =
  | "draft" | "issued" | "partially_paid" | "paid" | "overdue" | "cancelled";

export interface Invoice {
  id: string;
  invoice_number: string | null;
  organization_id: string;
  sales_order_id: string | null;
  invoice_date: string | null;
  due_date: string | null;
  payment_terms_days: number;
  status: "draft" | "issued" | "cancelled";
  origin: "system" | "migration";
  subtotal: string;
  discount_total: string;
  tax_total: string;
  grand_total: string;
  allocated: string;
  outstanding: string;
  derived_status: InvoiceDerivedStatus;
  notes: string | null;
  cancelled_reason: string | null;
  issued_at: string | null;
  pdf_document_id: string | null;
  created_at: string;
  items: InvoiceItem[];
}
