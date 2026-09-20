/**
 * Backup & data (SEC-13, DAT-01..17).
 *
 *   Backups   automatic after changes and at sign-in; "Back up now"; each one
 *             downloadable - the file is encrypted end to end, safe on a USB
 *             stick. Restore from a kept backup or a file from this device:
 *             verify (writes nothing) is the default, then merge or fresh.
 *             Another account's file is refused here: the server owner
 *             restores those with scripts/restore.py.
 *   Export    transactions as CSV - PLAINTEXT, and the screen says so before
 *             it downloads. One row per split.
 *   Import    a CSV, previewed first: columns mapped, problems by line,
 *             duplicates flagged. A file with any problem imports nothing.
 */
import { format, parseISO } from 'date-fns';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BudgetAppImportSheet } from '../components/BudgetAppImportSheet';
import { ScreenHeader } from '../components/ScreenHeader';
import { Button } from '../components/ui/Button';
import { Card, SectionTitle } from '../components/ui/Card';
import { Segmented } from '../components/ui/Segmented';
import { Sheet } from '../components/ui/Sheet';
import { ApiError, saveBlob } from '../lib/api';
import {
  backUpNow,
  downloadBackup,
  exportTransactions,
  fileSize,
  IMPORT_FIELDS,
  listBackups,
  fileToBase64,
  previewImport,
  restoreBackup,
  runImport,
  uploadBackup,
  type BackupList,
  type DateFormat,
  type ImportPreview,
  type RestoreMode,
  type RestoreReport,
  type UploadInfo,
} from '../lib/backups';
import { afterWrite, EVERYTHING } from '../lib/invalidate';
import { formatPHP } from '../lib/money';
import { localToday } from '../lib/transactions';
import { useLedgerStore } from '../stores/ledgerStore';

const when = (iso: string) => format(parseISO(iso), 'd MMM yyyy, h:mm a');
const TABLE_LABEL: Record<string, string> = {
  accounts: 'Accounts', categories: 'Categories', tags: 'Tags', budgets: 'Budget', budget_allocations: 'Budget categories',
  recurring_rules: 'Recurring', subscriptions: 'Subscriptions', savings_goals: 'Goals', user_preferences: 'Settings',
  transactions: 'Transactions', attachments: 'Receipts',
};

type Source = { kind: 'kept'; name: string; created_at: string } | { kind: 'upload'; info: UploadInfo };

/**
 * The column names on a CSV's first line, read here so the column pickers show
 * even when the server cannot preview yet - a bank's file rarely uses our
 * names, and "choose the column" is useless without something to choose from.
 */
function csvHeaders(text: string): string[] {
  const line = text.replace(/^﻿/, '').split(/\r?\n/, 1)[0] ?? '';
  const cells: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') {
      cells.push(cell.trim());
      cell = '';
    } else cell += ch;
  }
  cells.push(cell.trim());
  return cells.filter(Boolean);
}

function RestoreSheet({ source, onClose, onDone }: { source: Source | null; onClose: () => void; onDone: () => void }) {
  const [mode, setMode] = useState<RestoreMode>('verify');
  const [report, setReport] = useState<RestoreReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!source) return;
    setMode('verify');
    setReport(null);
    setError(null);
    setBusy(false);
  }, [source]);

  if (!source) return null;
  const otherAccount = source.kind === 'upload' && !source.info.same_account;
  const run = async () => {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const result = await restoreBackup({
        ...(source.kind === 'kept' ? { name: source.name } : { upload_id: source.info.upload_id }),
        mode,
      });
      setReport(result);
      if (result.mode !== 'verify') {
        // A restore replaces the lot - including the accounts and categories any
        // filter refers to, so the ledger goes back to unfiltered first.
        useLedgerStore.setState({ filters: {} });
        afterWrite(...EVERYTHING);
        onDone();
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'That did not work. Try again.');
    }
    setBusy(false);
  };

  const created = source.kind === 'kept' ? source.created_at : source.info.created_at;
  return (
    <Sheet open onClose={onClose} title="Restore">
      <div className="space-y-4 pb-2">
        <p className="text-footnote text-ink-2">
          Backup from {when(created)}
          {source.kind === 'upload' && ` · ${source.info.rows} rows · ${source.info.attachments} receipts`}
        </p>
        <Segmented<RestoreMode>
          label="Restore mode"
          value={mode}
          onChange={(next) => {
            setMode(next);
            setReport(null);
          }}
          options={[
            { value: 'verify', label: 'Check' },
            { value: 'merge', label: 'Add' },
            { value: 'fresh', label: 'Fresh' },
          ]}
        />
        <p className="text-footnote text-ink-2">
          {mode === 'verify'
            ? 'Opens every row, checks every link, and compares the backup with what you have now. Changes nothing.'
            : mode === 'merge'
              ? 'Adds what is in the backup and not here. Anything already here is left as it is.'
              : 'For an account with nothing in it yet — a new server, or a fresh sign-up.'}
        </p>

        {otherAccount && (
          <p className="rounded-2xl border-2 border-warn bg-warn/10 px-4 py-3 text-footnote text-ink">
            This backup belongs to a different account, so it can’t be restored from here. Whoever runs this server can
            restore it into your account with the restore script.
          </p>
        )}

        {error && <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

        {report && (
          <div className={`space-y-2 rounded-2xl px-4 py-3 ${report.ok && report.differences.length === 0 ? 'bg-ok/10' : 'bg-surface-2'}`}>
            <p className={`text-footnote font-semibold ${report.ok ? 'text-ok' : 'text-danger'}`}>
              {report.mode === 'verify'
                ? report.ok
                  ? report.differences.length === 0
                    ? '✓ The backup opens, and matches what you have now.'
                    : '✓ The backup opens and restores. It differs from what you have now:'
                  : 'This backup would not restore cleanly.'
                : `✓ Restored${report.attachments ? `, with ${report.attachments} receipts` : ''}.`}
            </p>
            {report.differences.map((d) => (
              <p key={d.table} className="text-footnote text-ink-2">
                {TABLE_LABEL[d.table] ?? d.table}: {d.only_in_backup} only in the backup · {d.only_in_live} only here
              </p>
            ))}
            {report.mode !== 'verify' &&
              report.tables.filter((t) => t.in_backup > 0).map((t) => (
                <p key={t.table} className="text-footnote text-ink-2">
                  {TABLE_LABEL[t.table] ?? t.table}: {t.restored} restored{t.skipped ? ` · ${t.skipped} already here` : ''}
                </p>
              ))}
            {report.unresolved.map((u) => <p key={u} className="text-footnote text-danger">Broken link: {u}</p>)}
            {report.missing_files > 0 && (
              <p className="text-footnote text-danger">{report.missing_files} receipt files are missing from the backup.</p>
            )}
          </div>
        )}

        <Button block size="lg" variant={mode === 'verify' ? 'primary' : 'danger'} disabled={busy || otherAccount}
          onClick={() => void run()}>
          {busy ? 'Working…' : mode === 'verify' ? 'Check this backup' : mode === 'merge' ? 'Add it to my data' : 'Restore into this account'}
        </Button>
      </div>
    </Sheet>
  );
}

function ImportSheet({ file, onClose }: { file: { name: string; text: string } | null; onClose: () => void }) {
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [dateFormat, setDateFormat] = useState<DateFormat>('YYYY-MM-DD');
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const check = useCallback(async (nextMapping: Record<string, string>, nextFormat: DateFormat) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const found = await previewImport({ csv: file.text, mapping: nextMapping, date_format: nextFormat });
      setPreview(found);
      setMapping(found.mapping);
    } catch (e) {
      // Keep the choices made so far: the fix is usually one more column picked.
      setPreview(null);
      setError(e instanceof ApiError ? e.message : 'That file could not be read.');
    }
    setBusy(false);
  }, [file]);

  useEffect(() => {
    if (!file) return;
    setMapping({});
    setDateFormat('YYYY-MM-DD');
    setPreview(null);
    setResult(null);
    void check({}, 'YYYY-MM-DD');
  }, [file, check]);

  if (!file) return null;
  const headers = preview?.headers ?? csvHeaders(file.text);

  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const done = await runImport({ csv: file.text, mapping, date_format: dateFormat, skip_duplicates: true });
      setResult(`${done.created} transaction${done.created === 1 ? '' : 's'} imported${done.skipped_duplicates ? `, ${done.skipped_duplicates} duplicates skipped` : ''}.`);
      setPreview(null);
      // An import can create accounts and categories as well as transactions.
      useLedgerStore.setState({ filters: {} });
      afterWrite(...EVERYTHING);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The import did not run.');
    }
    setBusy(false);
  };

  return (
    <Sheet open onClose={onClose} title="Import transactions">
      <div className="space-y-4 pb-2">
        <p className="truncate text-footnote text-ink-2">{file.name}</p>
        {headers.length > 0 && (
          <div className="space-y-2">
            <p className="text-footnote font-semibold text-ink-2">Which column holds…</p>
            {IMPORT_FIELDS.map(({ field, label, required }) => (
              <label key={field} className="flex items-center gap-3 text-footnote">
                <span className="w-32 shrink-0 text-ink-2">{label}{required ? ' *' : ''}</span>
                <select
                  value={mapping[field] ?? ''}
                  onChange={(e) => {
                    const next = { ...mapping };
                    if (e.target.value) next[field] = e.target.value;
                    else delete next[field];
                    setMapping(next);
                    void check(next, dateFormat);
                  }}
                  className="min-h-tap min-w-0 flex-1 rounded-xl border-2 border-stroke bg-surface px-2 text-body text-ink"
                >
                  <option value="">—</option>
                  {headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </label>
            ))}
            <Segmented<DateFormat>
              label="Date format"
              value={dateFormat}
              onChange={(next) => {
                setDateFormat(next);
                void check(mapping, next);
              }}
              options={[
                { value: 'YYYY-MM-DD', label: '2026-09-14' },
                { value: 'DD/MM/YYYY', label: '14/09/2026' },
                { value: 'MM/DD/YYYY', label: '09/14/2026' },
              ]}
            />
            <p className="text-caption text-ink-3">Without a Type column, a negative amount is spending and a positive one income.</p>
          </div>
        )}

        {error && <p className="rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}
        {result && <p className="rounded-2xl border-2 border-ok bg-ok/10 px-4 py-3 text-footnote font-semibold text-ok">✓ {result}</p>}

        {preview && (
          <div className="space-y-2">
            <p className="text-footnote text-ink-2">
              {preview.transactions} transactions in {preview.rows} rows · {preview.ready} to import
              {preview.duplicates > 0 && ` · ${preview.duplicates} already recorded (skipped)`}
            </p>
            {preview.errors.length > 0 && (
              <div className="space-y-1 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3">
                <p className="text-footnote font-semibold text-danger">
                  {preview.errors.length} row{preview.errors.length === 1 ? '' : 's'} to fix first — nothing is imported until then:
                </p>
                {preview.errors.slice(0, 12).map((issue) => (
                  <p key={`${issue.line}-${issue.message}`} className="text-footnote text-danger">Line {issue.line}: {issue.message}</p>
                ))}
              </div>
            )}
            {preview.entries.length > 0 && (
              <ul className="divide-y divide-stroke/80 rounded-card border-2 border-stroke bg-surface-2 px-3">
                {preview.entries.slice(0, 8).map((e) => (
                  <li key={e.line} className={`num flex min-h-10 items-center justify-between gap-2 text-footnote ${e.duplicate ? 'opacity-50' : ''}`}>
                    <span className="min-w-0 truncate">{e.txn_date} · {e.merchant ?? e.type} · {e.account}{e.duplicate ? ' · duplicate' : ''}</span>
                    <span className={`shrink-0 font-semibold ${e.type === 'income' ? 'text-ok' : ''}`}>{formatPHP(e.amount)}</span>
                  </li>
                ))}
              </ul>
            )}
            <Button block size="lg" disabled={busy || preview.errors.length > 0 || preview.ready === 0} onClick={() => void go()}>
              {preview.ready === 0 ? 'Nothing new to import' : `Import ${preview.ready} transaction${preview.ready === 1 ? '' : 's'}`}
            </Button>
          </div>
        )}
      </div>
    </Sheet>
  );
}

export function Backup() {
  const navigate = useNavigate();
  const [list, setList] = useState<BackupList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState<Source | null>(null);
  const [csvFile, setCsvFile] = useState<{ name: string; text: string } | null>(null);
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [confirmExport, setConfirmExport] = useState(false);
  const backupInput = useRef<HTMLInputElement>(null);
  const csvInput = useRef<HTMLInputElement>(null);
  const budgetAppInput = useRef<HTMLInputElement>(null);
  const [budgetAppFile, setBudgetAppFile] = useState<{ name: string; data: string } | null>(null);

  const load = useCallback((signal?: AbortSignal) =>
    listBackups(signal).then((found) => {
      setList(found);
      setError(null);
    }).catch((e: Error) => e.name !== 'AbortError' && setError(e.message)), []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const act = async (action: () => Promise<unknown>, failed: string) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : failed);
    }
    setBusy(false);
  };

  const latest = list?.latest_at;
  return (
    <>
      <ScreenHeader
        title="Backup & data"
        subtitle={<button type="button" className="text-accent-ink" onClick={() => navigate('/more')}>‹ More</button>}
      />
      {error && <p className="mb-3 rounded-2xl border-2 border-danger bg-danger/10 px-4 py-3 text-footnote text-danger">{error}</p>}

      <Card>
        <p className="text-footnote font-medium text-ink-2">Last backup</p>
        <p className="text-headline">{latest ? when(latest) : 'None yet'}</p>
        <p className="mt-1 text-footnote text-ink-2">
          {list?.automatic
            ? `A backup is made ${list.debounce_minutes} minutes after you change something, and when you sign in if the last is over ${list.interval_hours} hours old.`
            : 'Automatic backup is off on this server — use Back up now.'}
        </p>
        <Button className="mt-3" block disabled={busy} onClick={() => void act(async () => { await backUpNow(); await load(); }, 'The backup did not run.')}>
          Back up now
        </Button>
        <p className="mt-2 text-caption text-ink-3">
          Every backup is encrypted end to end — safe to keep on a USB stick or in cloud storage. It opens with this
          server’s key, here or on a new server set up with the same key.
        </p>
      </Card>

      {list && list.backups.length > 0 && (
        <>
          <SectionTitle>Kept on the server · {list.retention_days} days</SectionTitle>
          <div className="divide-y divide-stroke/80 overflow-hidden rounded-card bg-surface shadow-card">
            {list.backups.map((b) => (
              <div key={b.name} className="flex min-h-14 items-center gap-2 px-4 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body">{when(b.created_at)}</span>
                  <span className="block text-footnote text-ink-3">{b.rows} rows · {b.attachments} receipts · {fileSize(b.size)}</span>
                </span>
                <Button variant="ghost" disabled={busy} onClick={() => void act(async () => saveBlob(await downloadBackup(b.name), b.name), 'The download did not start.')}>
                  Save
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => setSource({ kind: 'kept', name: b.name, created_at: b.created_at })}>
                  Restore
                </Button>
              </div>
            ))}
          </div>
        </>
      )}
      <Button className="mt-3" variant="secondary" block disabled={busy} onClick={() => backupInput.current?.click()}>
        Restore from a file on this device
      </Button>
      <input ref={backupInput} type="file" accept=".budgetbak" className="hidden"
        onChange={(e) => {
          const chosen = e.target.files?.[0];
          e.target.value = '';
          if (chosen) void act(async () => setSource({ kind: 'upload', info: await uploadBackup(chosen) }), 'That file could not be read.');
        }} />

      <SectionTitle>Export to CSV</SectionTitle>
      <Card className="space-y-3">
        <p className="rounded-card border-2 border-warn bg-warn/10 px-3 py-2 text-footnote font-semibold text-warn">
          A CSV is not encrypted. Anyone who opens the file can read every amount, merchant and note in it.
        </p>
        <p className="text-footnote text-ink-2">
          For Excel or another app. One row per split, so a split purchase is several rows sharing a transaction id — the row
          count will be more than your number of transactions.
        </p>
        <div className="grid grid-cols-2 gap-3">
          {([['From', from, setFrom], ['To', to, setTo]] as const).map(([label, value, set]) => (
            <label key={label} className="text-footnote font-semibold text-ink-2">
              {label}
              <input type="date" value={value} onChange={(e) => set(e.target.value)}
                className="mt-1.5 block min-h-12 w-full rounded-xl border-2 border-stroke bg-surface px-3 text-body font-normal text-ink" />
            </label>
          ))}
        </div>
        {confirmExport ? (
          <div className="grid grid-cols-2 gap-2">
            <Button variant="ghost" onClick={() => setConfirmExport(false)}>Cancel</Button>
            <Button disabled={busy} onClick={() => void act(async () => {
              saveBlob(await exportTransactions(from || undefined, to || undefined), `budget-transactions-${localToday()}.csv`);
              setConfirmExport(false);
            }, 'The export did not run.')}>
              Download anyway
            </Button>
          </div>
        ) : (
          <Button block variant="secondary" onClick={() => setConfirmExport(true)}>Export transactions</Button>
        )}
      </Card>

      <SectionTitle>Import from Budget App</SectionTitle>
      <Card>
        <p className="text-footnote text-ink-2">
          The .xlsx backup the Budget phone app makes. Accounts, categories, every transaction and who owes what come across; you
          type each account’s balance today so it matches exactly. Import again later and only what is new is added.
        </p>
        <Button className="mt-3" block variant="secondary" disabled={busy} onClick={() => budgetAppInput.current?.click()}>
          Choose the .xlsx backup
        </Button>
        <input ref={budgetAppInput} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="hidden"
          onChange={(e) => {
            const chosen = e.target.files?.[0];
            e.target.value = '';
            if (chosen) void act(async () => setBudgetAppFile({ name: chosen.name, data: await fileToBase64(chosen) }), 'That file could not be read.');
          }} />
      </Card>

      <SectionTitle>Import from CSV</SectionTitle>
      <Card>
        <p className="text-footnote text-ink-2">
          Your own export, or a bank’s CSV. You see every transaction and every problem before anything is saved; duplicates of
          what you already have are skipped. Accounts and categories must exist first, by the same names.
        </p>
        <Button className="mt-3" block variant="secondary" onClick={() => csvInput.current?.click()}>Choose a CSV file</Button>
        <input ref={csvInput} type="file" accept=".csv,text/csv" className="hidden"
          onChange={(e) => {
            const chosen = e.target.files?.[0];
            e.target.value = '';
            if (chosen) void chosen.text().then((text) => setCsvFile({ name: chosen.name, text }));
          }} />
      </Card>

      <RestoreSheet source={source} onClose={() => setSource(null)} onDone={() => void load()} />
      <ImportSheet file={csvFile} onClose={() => setCsvFile(null)} />
      <BudgetAppImportSheet file={budgetAppFile} onClose={() => setBudgetAppFile(null)} />
    </>
  );
}
