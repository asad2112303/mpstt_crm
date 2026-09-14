/** Website intake — rows of public.quotation_requests, served by FastAPI. */

export type QuotationRequestStatus =
  | "new"
  | "contacted"
  | "quotation_preparing"
  | "quotation_sent"
  | "won"
  | "lost"
  | "closed";

export const QUOTATION_REQUEST_STATUSES: QuotationRequestStatus[] = [
  "new",
  "contacted",
  "quotation_preparing",
  "quotation_sent",
  "won",
  "lost",
  "closed",
];

export const QUOTATION_REQUEST_STATUS_LABELS: Record<QuotationRequestStatus, string> = {
  new: "New",
  contacted: "Contacted",
  quotation_preparing: "Preparing quotation",
  quotation_sent: "Quotation sent",
  won: "Won",
  lost: "Lost",
  closed: "Closed",
};

/** Only the website writes these; the CRM writes status/internal_notes/contacted_at. */
export interface QuotationRequest {
  id: string;
  reference: string;
  full_name: string;
  organization: string;
  phone: string;
  email: string | null;
  organization_type: string | null;
  requirement: string;
  consent: boolean;
  consent_at: string;
  source_page: string | null;
  product_slug: string | null;
  category_slug: string | null;
  product_name: string | null;
  intent: string | null;
  status: QuotationRequestStatus;
  internal_notes: string | null;
  contacted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface QuotationRequestSummary {
  total: number;
  by_status: Record<QuotationRequestStatus, number>;
  new_count: number;
  open_count: number;
}
