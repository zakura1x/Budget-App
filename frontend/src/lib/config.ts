/**
 * Where the app lives, read from the meta tags the server renders
 * (app/web/templates/index.html) - so the bundle never hard-codes /ZBDGT.
 */

function meta(name: string, fallback: string): string {
  const value = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content?.trim();
  return value ? value.replace(/\/+$/, '') : fallback;
}

export const BASE_URL = meta('app-base', '/ZBDGT');
export const API_PREFIX = meta('app-api', '/ZBDGT/api/v1');
