/**
 * Receipts (TXN-15). Encrypted on the server; decrypted into a blob in page
 * memory only to show it, and the object URL is revoked when it leaves the
 * screen (SEC-29).
 */
import { api, apiBlob } from './api';

export interface Attachment {
  id: number;
  transaction_id: number;
  filename: string;
  mime: string;
  size: number;
}

export const ACCEPTED = 'image/jpeg,image/png,image/heic,application/pdf,.jpg,.jpeg,.png,.heic,.pdf';

export const attachReceipt = (transactionId: number, file: File) =>
  api<Attachment>(`/transactions/${transactionId}/attachment`, {
    method: 'POST',
    raw: file,
    // The name goes in a header, never the URL - IIS logs URLs.
    headers: { 'X-Filename': encodeURIComponent(file.name) },
  });

export const getReceipt = (attachmentId: number) => apiBlob(`/attachments/${attachmentId}`);

export const removeReceipt = (transactionId: number) =>
  api<void>(`/transactions/${transactionId}/attachment`, { method: 'DELETE' });
