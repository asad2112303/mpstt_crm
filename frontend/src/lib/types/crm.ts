export type OrgType =
  | "hospital" | "clinic" | "laboratory" | "pharmacy"
  | "industry" | "ngo" | "government" | "other";

export type ProspectStage =
  | "targeted" | "visited" | "requirement_collected" | "sample_provided"
  | "quotation_sent" | "negotiation" | "lost" | "deferred" | "won";

export const STAGE_LABELS: Record<ProspectStage, string> = {
  targeted: "Targeted",
  visited: "Visited",
  requirement_collected: "Requirement collected",
  sample_provided: "Sample provided",
  quotation_sent: "Quotation sent",
  negotiation: "Negotiation",
  lost: "Lost",
  deferred: "Deferred",
  won: "Won",
};

export const ORG_TYPE_LABELS: Record<OrgType, string> = {
  hospital: "Hospital",
  clinic: "Clinic",
  laboratory: "Laboratory",
  pharmacy: "Pharmacy",
  industry: "Industry",
  ngo: "NGO",
  government: "Government",
  other: "Other",
};

export interface ProspectProfile {
  stage: ProspectStage;
  assigned_user_id: string | null;
  first_contact_date: string | null;
  last_activity_at: string | null;
  next_action_summary: string | null;
  lost_reason: string | null;
  deferred_reason: string | null;
  reactivation_date: string | null;
}

export interface CustomerProfile {
  customer_code: string;
  customer_since: string;
  payment_terms_days: number;
  credit_limit: string | null;
  account_status: string;
  billing_notes: string | null;
  purchasing_notes: string | null;
}

export interface Organization {
  id: string;
  org_code: string;
  name: string;
  legal_name: string | null;
  org_type: OrgType;
  lifecycle_status: "prospect" | "customer";
  city: string | null;
  area: string | null;
  source: string | null;
  phone: string | null;
  ntn: string | null;
  notes: string | null;
  is_active: boolean;
  converted_at: string | null;
  created_at: string;
  prospect_profile: ProspectProfile | null;
  customer_profile: CustomerProfile | null;
}

export interface Branch {
  id: string;
  organization_id: string;
  branch_name: string;
  area: string | null;
  city: string | null;
  delivery_address: string | null;
  billing_address: string | null;
  map_url: string | null;
  route_cluster: string | null;
  is_primary: boolean;
  is_active: boolean;
}

export interface Contact {
  id: string;
  organization_id: string;
  branch_id: string | null;
  full_name: string;
  designation: string | null;
  department: string | null;
  phone_primary: string | null;
  phone_alt: string | null;
  whatsapp: string | null;
  email: string | null;
  preferred_channel: string | null;
  is_primary: boolean;
  is_active: boolean;
}

export interface Activity {
  id: string;
  organization_id: string;
  contact_id: string | null;
  activity_type: "visit" | "call" | "whatsapp" | "email" | "meeting" | "follow_up";
  happened_at: string;
  outcome: string | null;
  notes: string | null;
  products_discussed: string | null;
  created_by: string | null;
  created_at: string;
}

export interface Task {
  id: string;
  organization_id: string | null;
  assigned_user_id: string | null;
  task_type: string;
  title: string;
  due_at: string;
  priority: "low" | "normal" | "high";
  status: "open" | "done" | "cancelled";
  completion_outcome: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ProductProfileRow {
  id: string;
  organization_id: string;
  product_id: string;
  product_variant_id: string | null;
  frequency: string | null;
  min_quantity: string | null;
  max_quantity: string | null;
  uom_id: string | null;
  current_supplier: string | null;
  current_rate: string | null;
  specification_notes: string | null;
  is_active: boolean;
  /** Resolved by the API so the list renders without a catalogue lookup. */
  product_name: string | null;
  product_sku: string | null;
  variant_name: string | null;
  uom_code: string | null;
}

export interface SampleRow {
  id: string;
  organization_id: string;
  product_id: string;
  product_variant_id: string | null;
  quantity: string;
  uom_id: string | null;
  issued_at: string;
  receiver_name: string | null;
  feedback_due_date: string | null;
  status: "issued" | "feedback_received" | "converted" | "closed";
  feedback: string | null;
  created_at: string;
}

export interface PriceRow {
  id: string;
  organization_id: string;
  product_id: string;
  product_variant_id: string | null;
  price_type: "quoted" | "agreed" | "list";
  unit_price: string;
  uom_id: string | null;
  effective_from: string;
  effective_to: string | null;
  source_reference: string | null;
  created_at: string;
}

export interface ActionQueueRow {
  organization_id: string;
  org_code: string;
  name: string;
  city: string | null;
  area: string | null;
  stage: ProspectStage;
  assigned_user_id: string | null;
  last_activity_at: string | null;
  next_action_summary: string | null;
  next_task_due_at: string | null;
  open_task_count: number;
  missing_next_action: boolean;
  overdue: boolean;
  days_since_last_activity: number | null;
}

export function formatKarachi(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-PK", {
    timeZone: "Asia/Karachi",
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  });
}
