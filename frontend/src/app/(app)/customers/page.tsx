"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Users2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { ORG_TYPE_LABELS, formatKarachi, type Organization } from "@/lib/types/crm";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

export default function CustomersPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ["customers", { search, page }],
    queryFn: async () =>
      await api<Organization[]>("/api/v1/customers", {
        searchParams: { search: search || undefined, page, page_size: 25 },
      }),
  });

  const total = data?.meta.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 25));

  return (
    <main className="space-y-6 p-6">
      <PageHeader
        title="Customers"
        description="Converted organizations — full history preserved from prospect days."
      />
      <Input
        placeholder="Search name, customer code, city…"
        className="w-72"
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        aria-label="Search customers"
      />

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : error ? (
        <p role="alert" className="text-sm text-destructive">
          Failed to load customers: {error instanceof ApiError ? error.message : "unknown error"}
        </p>
      ) : !data?.data.length ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-12 text-center">
          <Users2 className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            No customers yet. A prospect becomes a customer with its first confirmed order.
          </p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Customer code</TableHead>
                  <TableHead>Organization</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>City</TableHead>
                  <TableHead>Customer since</TableHead>
                  <TableHead>Terms</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-mono text-xs">
                      {c.customer_profile?.customer_code}
                    </TableCell>
                    <TableCell>
                      <Link href={`/customers/${c.id}`}
                        className="font-medium text-primary hover:underline">
                        {c.name}
                      </Link>
                    </TableCell>
                    <TableCell>{ORG_TYPE_LABELS[c.org_type]}</TableCell>
                    <TableCell className="text-muted-foreground">{c.city ?? "—"}</TableCell>
                    <TableCell>{c.customer_profile?.customer_since}</TableCell>
                    <TableCell>{c.customer_profile?.payment_terms_days} days</TableCell>
                    <TableCell>
                      <Badge variant={c.customer_profile?.account_status === "active" ? "outline" : "destructive"}>
                        {c.customer_profile?.account_status}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} customers</span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <span>Page {page} of {pages}</span>
              <Button variant="outline" size="sm" disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
