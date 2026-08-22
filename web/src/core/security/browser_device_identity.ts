/**
 * Browser Device Identity.
 * Produces a stable pseudo-random fingerprint per browser, persisted in localStorage.
 */

const STORAGE_KEY = 'assistme_device_fingerprint';

function generateFingerprint(): string {
  const chars = 'abcdef0123456789';
  let id = '';
  for (let i = 0; i < 32; i++) {
    id += chars[Math.floor(Math.random() * chars.length)];
  }
  return `browser-${id}`;
}

export function getBrowserFingerprint(): string {
  try {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (existing && existing.length >= 16) {
      return existing;
    }
    const fresh = generateFingerprint();
    localStorage.setItem(STORAGE_KEY, fresh);
    return fresh;
  } catch {
    return generateFingerprint();
  }
}