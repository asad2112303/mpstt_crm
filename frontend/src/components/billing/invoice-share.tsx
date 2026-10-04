"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Download, Printer, Share2 } from "lucide-react";
import { apiBlob, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";

/**
 * Download, print and share the finalized invoice.
 *
 * The PDF is the same document on every device — generated server-side from
 * the snapshot frozen at issue — so a phone and a desktop hand the customer
 * an identical file. Nothing is ever sent automatically: sharing always goes
 * through the operating system's own share sheet, where the user picks the
 * app and the recipient.
 */
/** Any server-rendered PDF as a file, with the same auth as any other call. */
export async function fetchDocument(path: string, filename: string): Promise<File> {
  const blob = await apiBlob(path);
  return new File([blob], `${filename}.pdf`, { type: "application/pdf" });
}

export async function downloadDocument(path: string, filename: string) {
  const file = await fetchDocument(path, filename);
  const url = URL.createObjectURL(file);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.name;
  a.click();
  URL.revokeObjectURL(url);
}

export async function printDocument(path: string, filename: string) {
  const file = await fetchDocument(path, filename);
  const url = URL.createObjectURL(file);
  // A tab rather than a hidden iframe: mobile browsers refuse to print from
  // iframes, and this leaves the user somewhere sensible either way.
  const w = window.open(url, "_blank");
  if (!w) {
    toast.error("Allow pop-ups to print, or download the PDF instead.");
    return;
  }
  w.addEventListener("load", () => w.print(), { once: true });
}

const invoicePath = (id: string) => `/api/v1/invoices/${id}/pdf`;

export const fetchInvoiceFile = (id: string, number: string) =>
  fetchDocument(invoicePath(id), number);
export const downloadInvoice = (id: string, number: string) =>
  downloadDocument(invoicePath(id), number);
export const printInvoice = (id: string, number: string) =>
  printDocument(invoicePath(id), number);

export function InvoiceActions({
  invoiceId,
  invoiceNumber,
  className,
  pdfPath,
  label = "The customer\u2019s PDF shows prices only — purchase cost and profit are never on it.",
}: {
  invoiceId: string;
  invoiceNumber: string;
  className?: string;
  /** Defaults to the invoice PDF; a rate list passes its own path. */
  pdfPath?: string;
  label?: string;
}) {
  const [busy, setBusy] = useState<"download" | "print" | "share" | null>(null);

  const path = pdfPath ?? invoicePath(invoiceId);
  const getFile = () => fetchDocument(path, invoiceNumber);

  function fail(e: unknown) {
    toast.error(e instanceof ApiError ? e.message : "Could not prepare the invoice.");
  }

  async function download() {
    setBusy("download");
    try {
      await downloadDocument(path, invoiceNumber);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function print() {
    setBusy("print");
    try {
      await printDocument(path, invoiceNumber);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function share() {
    setBusy("share");
    try {
      const file = await getFile();
      // Share the file itself where the device supports it; fall back to a
      // download rather than pretending the share worked.
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: `Invoice ${invoiceNumber}`,
          text: `Invoice ${invoiceNumber}`,
        });
      } else {
        await download();
        toast.info("Sharing is not available on this device — the PDF was downloaded.");
      }
    } catch (e) {
      // A cancelled share sheet is not a failure.
      if ((e as Error)?.name !== "AbortError") fail(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={className}>
      <div className="grid grid-cols-3 gap-2">
        <Button variant="outline" disabled={busy !== null} onClick={() => void download()}>
          <Download className="mr-1.5 h-4 w-4" aria-hidden />
          {busy === "download" ? "…" : "PDF"}
        </Button>
        <Button variant="outline" disabled={busy !== null} onClick={() => void print()}>
          <Printer className="mr-1.5 h-4 w-4" aria-hidden />
          Print
        </Button>
        <Button variant="outline" disabled={busy !== null} onClick={() => void share()}>
          <Share2 className="mr-1.5 h-4 w-4" aria-hidden />
          Share
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
