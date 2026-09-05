"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { PageHeader } from "@/components/page-header";
import { RequireAdmin } from "@/components/require-admin";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface UserRow {
  id: string;
  full_name: string;
  email: string | null;
  role: "admin" | "user";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

function InviteDialog() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<"admin" | "user">("user");
  const [mode, setMode] = useState<"password" | "invite">("password");
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  const invite = useMutation({
    mutationFn: () =>
      api<UserRow & { temporary_password: string | null }>(
        "/api/v1/admin/users/invite",
        { method: "POST", body: { email, full_name: fullName, role, mode } },
      ),
    onSuccess: (resp) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      const password = resp.data.temporary_password;
      if (password) {
        setCreated({ email, password }); // shown once; the CRM never stores it
      } else {
        toast.success(`Invitation email sent to ${email}`);
        setOpen(false);
      }
      setEmail("");
      setFullName("");
      setRole("user");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not add the user."),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        <UserPlus className="h-4 w-4" aria-hidden />
        Invite user
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{created ? "User created" : "Add a user"}</DialogTitle>
          <DialogDescription>
            {created
              ? "Copy these credentials now — the password is shown only once."
              : "There is no public signup: accounts are created here by an administrator."}
          </DialogDescription>
        </DialogHeader>
        {created ? (
          <div className="space-y-3">
            <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
              <p className="flex justify-between gap-4">
                <span className="text-muted-foreground">Email</span>
                <span className="font-medium">{created.email}</span>
              </p>
              <p className="mt-1 flex justify-between gap-4">
                <span className="text-muted-foreground">Temporary password</span>
                <span className="font-mono font-medium">{created.password}</span>
              </p>
            </div>
            <p className="text-xs text-muted-foreground">
              Share these over a trusted channel and ask the user to change the
              password after signing in. The CRM never stores it.
            </p>
            <DialogFooter>
              <Button variant="outline"
                onClick={() => {
                  void navigator.clipboard?.writeText(
                    `${created.email} / ${created.password}`,
                  );
                  toast.success("Credentials copied");
                }}>
                Copy
              </Button>
              <Button onClick={() => { setCreated(null); setOpen(false); }}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
        <>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            invite.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="invite-name">Full name</Label>
            <Input
              id="invite-name"
              required
              minLength={2}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="invite-role">Role</Label>
            <Select value={role} onValueChange={(v) => setRole(v as "admin" | "user")}>
              <SelectTrigger id="invite-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">Operational user</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="invite-mode">How should they get access?</Label>
            <Select value={mode}
              onValueChange={(v) => setMode((v as "password" | "invite") ?? "password")}>
              <SelectTrigger id="invite-mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="password">Set a password now (recommended)</SelectItem>
                <SelectItem value="invite">Send an invitation email</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {mode === "password"
                ? "Creates the login immediately and shows a one-time password to hand over — no email delivery needed."
                : "Needs working email delivery in the Supabase project; the built-in sender is rate limited."}
            </p>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={invite.isPending || !email || !fullName}>
              {invite.isPending
                ? "Adding…"
                : mode === "password" ? "Create user" : "Send invitation"}
            </Button>
          </DialogFooter>
        </form>
        </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function UsersTable() {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: async () => (await api<UserRow[]>("/api/v1/admin/users")).data,
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<UserRow> }) =>
      api(`/api/v1/admin/users/${id}`, { method: "PATCH", body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("User updated");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Update failed."),
  });

  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (error)
    return (
      <p role="alert" className="text-sm text-destructive">
        Failed to load users: {error instanceof ApiError ? error.message : "unknown error"}
      </p>
    );
  if (!data?.length)
    return <p className="text-sm text-muted-foreground">No users yet.</p>;

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Last sign-in</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((u) => (
            <TableRow key={u.id}>
              <TableCell className="font-medium">{u.full_name}</TableCell>
              <TableCell className="text-muted-foreground">{u.email}</TableCell>
              <TableCell>
                <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                  {u.role === "admin" ? "Admin" : "User"}
                </Badge>
              </TableCell>
              <TableCell>
                <Badge variant={u.is_active ? "outline" : "destructive"}>
                  {u.is_active ? "Active" : "Disabled"}
                </Badge>
              </TableCell>
              <TableCell className="text-muted-foreground">
                {u.last_login_at
                  ? new Date(u.last_login_at).toLocaleString("en-PK", {
                      timeZone: "Asia/Karachi",
                    })
                  : "Never"}
              </TableCell>
              <TableCell className="text-right">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={patch.isPending || u.id === me?.id}
                  onClick={() =>
                    patch.mutate({ id: u.id, body: { is_active: !u.is_active } })
                  }
                >
                  {u.is_active ? "Deactivate" : "Activate"}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function AdminUsersPage() {
  return (
    <RequireAdmin>
      <main className="space-y-6 p-6">
        <PageHeader
          title="Users"
          description="Invite, activate, and manage CRM accounts."
          actions={<InviteDialog />}
        />
        <UsersTable />
      </main>
    </RequireAdmin>
  );
}
