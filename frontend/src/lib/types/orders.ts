export interface OrderItem {
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

export type OrderStatus =
  | "draft" | "confirmed" | "preparing" | "ready"
  | "partially_delivered" | "fully_delivered" | "completed" | "cancelled";

export interface Order {
  id: string;
  order_number: string;
  organization_id: string;
  branch_id: string | null;
  source_quotation_id: string | null;
  is_direct_po: boolean;
  customer_po_number: string | null;
  order_date: string;
  expected_delivery_date: string | null;
  status: OrderStatus;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  grand_total: string;
  notes: string | null;
  cancelled_reason: string | null;
  created_at: string;
  items: OrderItem[];
}

export interface StockRow {
  warehouse_id: string;
  warehouse_code: string;
  product_variant_id: string;
  sku: string;
  product_name: string;
  variant_name: string;
  variant_code: string;
  uom_code: string;
  on_hand: string;
  reserved: string;
  available: string;
}

export interface WarehouseRow {
  id: string;
  code: string;
  name: string;
  address: string | null;
  is_active: boolean;
}

export interface MovementRow {
  id: string;
  warehouse_id: string;
  product_variant_id: string;
  product: string;
  quantity: string;
  movement_type: string;
  reference_type: string | null;
  reference_id: string | null;
  notes: string | null;
  movement_at: string;
}
