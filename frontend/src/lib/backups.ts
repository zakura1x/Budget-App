/**
 * /backups and /data - the encrypted backup, restore, and CSV (DAT-01..17).
 *
 * A .budgetbak is ciphertext end to end; downloading one is safe anywhere.
 * A CSV is plaintext, and the screen says so before it downloads.
 */
import { api, apiBlob } from './api';

export interface BackupInfo {
  name: string;
  created_at: string;
  size: number;
  rows: number;
  attachments: number;
}

export interface BackupList {
  backups: BackupInfo[];
  latest_at: string | null;
  automatic: boolean;
  debounce_minutes: number;
  interval_hours: number;
  retention_days: number;
}

export interface UploadInfo {
  upload_id: string;
  created_at: string;
  rows: number;
  attachments: number;
  /** False: the file is another account's - only the restore script on the server can restore it. */
  same_account: boolean;
}

export type RestoreMode = 'verify' | 'merge' | 'fresh';

export interface RestoreReport {
  mode: RestoreMode;
  tables: { table: string; in_backup: number; restored: number; skipped: number }[];
  attachments: number;
  missing_files: number;
  unresolved: string[];
  differences: { table: string; only_in_backup: number; only_in_live: number }[];
  ok: boolean;
}

export type DateFormat = 'YYYY-MM-DD' | 'MM/DD/YYYY' | 'DD/MM/YYYY';

export interface ImportPreview {
  rows: number;
  transactions: number;
  ready: number;
  duplicates: number;
  errors: { line: number; message: string }[];
  headers: string[];
  mapping: Record<string, string>;
  entries: { line: number; txn_date: string; type: string; amount: string; account: string; merchant: string | null; duplicate: boolean }[];
}

export const IMPORT_FIELDS: { field: string; label: string; required?: boolean }[] = [
  { field: 'date', label: 'Date', required: true },
  { field: 'amount', label: 'Amount', required: true },
  { field: 'account', label: 'Account', required: true },
  { field: 'category', label: 'Category' },
  { field: 'type', label: 'Type' },
  { field: 'merchant', label: 'Merchant' },
  { field: 'notes', label: 'Notes' },
  { field: 'parent_category', label: 'Parent category' },
  { field: 'counter_account', label: 'Transfer to' },
  { field: 'txn_id', label: 'Transaction id (splits)' },
  { field: 'split_amount', label: 'Split amount' },
  { field: 'split_note', label: 'Split note' },
  { field: 'tags', label: 'Tags' },
];

export const listBackups = (signal?: AbortSignal) => api<BackupList>('/backups', { signal });

export const backUpNow = () => api<BackupInfo>('/backups', { method: 'POST' });

export const downloadBackup = (name: string) => apiBlob(`/backups/${encodeURIComponent(name)}/download`);

export const uploadBackup = (file: Blob) => api<UploadInfo>('/backups/upload', { method: 'POST', raw: file });

export const restoreBackup = (body: { name?: string; upload_id?: string; mode: RestoreMode }) =>
  api<RestoreReport>('/backups/restore', { method: 'POST', body });

export function exportTransactions(from?: string, to?: string): Promise<Blob> {
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  const query = params.toString();
  return apiBlob(`/data/transactions.csv${query ? `?${query}` : ''}`);
}

export const previewImport = (body: { csv: string; mapping: Record<string, string>; date_format: DateFormat }) =>
  api<ImportPreview>('/data/import/preview', { method: 'POST', body });

export const runImport = (body: { csv: string; mapping: Record<string, string>; date_format: DateFormat; skip_duplicates: boolean }) =>
  api<{ created: number; skipped_duplicates: number }>('/data/import', { method: 'POST', body });

/** "1.2 MB" - for a file size, never money. */
export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
