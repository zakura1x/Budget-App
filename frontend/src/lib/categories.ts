/**
 * /categories - types and calls.
 *
 * Deleting one can come back 409 CONFLICT with a usage count: the server is
 * asking where those transactions should go, not reporting a failure
 * (CAT-08). `usageFrom` reads that count off the problem body so the screen
 * can ask the question instead of showing an error.
 */
import { api, ApiError } from './api';

export type CategoryKind = 'expense' | 'income';

export interface Category {
  id: number;
  name: string;
  kind: CategoryKind;
  parent_id: number | null;
  icon: string;
  colour: string;
  sort_order: number;
  archived: boolean;
  usage: number;
  children: Category[];
}

export interface CategoryDraft {
  name: string;
  kind: CategoryKind;
  parent_id?: number | null;
  icon?: string;
  colour?: string;
}

export interface Deleted {
  deleted: number[];
  transactions_moved: number;
  reassigned_to: number | null;
}

export const listCategories = (signal?: AbortSignal) =>
  api<Category[]>('/categories?with_usage=true', { signal });

export const createCategory = (body: CategoryDraft) =>
  api<Category>('/categories', { method: 'POST', body });

export const updateCategory = (id: number, body: CategoryDraft) =>
  api<Category>(`/categories/${id}`, { method: 'PATCH', body });

export const reorderCategories = (orderedIds: number[]) =>
  api<Category[]>('/categories/reorder', { method: 'POST', body: { ordered_ids: orderedIds } });

export const deleteCategory = (id: number, reassignTo?: number) =>
  api<Deleted>(`/categories/${id}${reassignTo ? `?reassign_to=${reassignTo}` : ''}`, { method: 'DELETE' });

/** The transaction count on a 409, or null if this was a different error. */
export function usageFrom(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.code !== 'CONFLICT') return null;
  const usage = error.body.usage;
  return typeof usage === 'number' ? usage : null;
}

/** The tree flattened for reassignment pickers: parents, then their children. */
export function flatten(tree: Category[]): Category[] {
  return tree.flatMap((parent) => [parent, ...parent.children]);
}
