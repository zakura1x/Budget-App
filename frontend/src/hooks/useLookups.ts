/**
 * Accounts, categories and tags by id - what a transaction row needs to show a
 * name and a colour instead of a number. Fetched when the screen mounts and
 * again whenever the ledger changes (a write can move a balance), held in
 * component state only (SEC-29).
 */
import { useEffect, useState } from 'react';
import { listAccounts, type Account } from '../lib/accounts';
import { flatten, listCategories, type Category } from '../lib/categories';
import { listTags, type Tag } from '../lib/tags';
import { useLedgerStore } from '../stores/ledgerStore';

export interface Lookups {
  accounts: Account[];
  tree: Category[];
  tags: Tag[];
  accountById: Map<number, Account>;
  categoryById: Map<number, Category>;
  tagById: Map<number, Tag>;
  ready: boolean;
}

export function useLookups(): Lookups {
  const version = useLedgerStore((s) => s.version);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [tree, setTree] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listAccounts(controller.signal), listCategories(controller.signal), listTags(controller.signal)])
      .then(([accountList, categories, tagList]) => {
        setAccounts(accountList.accounts);
        setTree(categories);
        setTags(tagList);
        setReady(true);
      })
      .catch(() => {
        /* rows fall back to plain labels; the ledger itself reports errors */
      });
    return () => controller.abort();
  }, [version]);

  return {
    accounts,
    tree,
    tags,
    accountById: new Map(accounts.map((a) => [a.id, a])),
    categoryById: new Map(flatten(tree).map((c) => [c.id, c])),
    tagById: new Map(tags.map((t) => [t.id, t])),
    ready,
  };
}
