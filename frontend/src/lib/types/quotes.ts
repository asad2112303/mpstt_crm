export interface QuoteItem {
  id: string;
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

export type QuoteStatus =
  | "draft" | "sent" | "accepted" | "rejected"
  | "superseded" | "converted" | "cancelled";

export interface Quote {
  id: string;
  quotation_number: string;
  revision_no: number;
  parent_quotation_id: string | null;
  organization_id: string;
  branch_id: string | null;
  contact_id: string | null;
  quote_date: string;
  valid_until: string | null;
  status: QuoteStatus;
  effective_status: QuoteStatus | "expired";
  terms: string | null;
  notes: string | null;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  grand_total: string;
  pdf_document_id: string | null;
  sent_at: string | null;
  accepted_at: string | null;
  rejected_reason: string | null;
  converted_order_id: string | null;
  created_at: string;
  items: QuoteItem[];
}
