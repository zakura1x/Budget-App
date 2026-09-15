/**
 * /tags - types and calls (TXN-10).
 *
 * A tag cuts across categories ("Boracay trip"). Deleting one needs no
 * question: the server takes its id out of every transaction and says how many.
 */
import { api } from './api';

export interface Tag {
  id: number;
  name: string;
  colour: string;
  usage: number;
}

export interface TagDraft {
  name: string;
  colour?: string;
}

export const listTags = (signal?: AbortSignal) => api<Tag[]>('/tags?with_usage=true', { signal });

export const createTag = (body: TagDraft) => api<Tag>('/tags', { method: 'POST', body });

export const updateTag = (id: number, body: TagDraft) => api<Tag>(`/tags/${id}`, { method: 'PATCH', body });

export const deleteTag = (id: number) =>
  api<{ deleted: number; transactions_untagged: number }>(`/tags/${id}`, { method: 'DELETE' });
