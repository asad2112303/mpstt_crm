import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function UnauthorizedPage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
      <ShieldAlert className="h-10 w-10 text-warning" aria-hidden />
      <h1 className="text-xl font-semibold">Not authorized</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        You do not have permission to view that page. If you believe this is a
        mistake, contact your administrator.
      </p>
      <Button variant="outline" render={<Link href="/dashboard" />}>
        Back to dashboard
      </Button>
    </main>
  );
}
