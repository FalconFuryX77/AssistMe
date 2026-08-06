/**
 * Web Auth Token Store for Browser Applications.
 * Manages JWT Access Token and Refresh Token persistence in LocalStorage with Memory Fallbacks.
 */

export class WebAuthStore {
  private static readonly KEY_ACCESS_TOKEN = 'assistme_jwt_access';
  private static readonly KEY_REFRESH_TOKEN = 'assistme_jwt_refresh';

  private inMemoryAccessToken: string | null = null;
  private inMemoryRefreshToken: string | null = null;

  public saveTokens(accessToken: string, refreshToken: string): void {
    this.inMemoryAccessToken = accessToken;
    this.inMemoryRefreshToken = refreshToken;
    try {
      localStorage.setItem(WebAuthStore.KEY_ACCESS_TOKEN, accessToken);
      localStorage.setItem(WebAuthStore.KEY_REFRESH_TOKEN, refreshToken);
    } catch {
      // Memory fallback if localStorage is blocked by browser privacy settings
    }
  }

  public getAccessToken(): string | null {
    if (this.inMemoryAccessToken) return this.inMemoryAccessToken;
    try {
      return localStorage.getItem(WebAuthStore.KEY_ACCESS_TOKEN);
    } catch {
      return null;
    }
  }

  public getRefreshToken(): string | null {
    if (this.inMemoryRefreshToken) return this.inMemoryRefreshToken;
    try {
      return localStorage.getItem(WebAuthStore.KEY_REFRESH_TOKEN);
    } catch {
      return null;
    }
  }

  public clearTokens(): void {
    this.inMemoryAccessToken = null;
    this.inMemoryRefreshToken = null;
    try {
      localStorage.removeItem(WebAuthStore.KEY_ACCESS_TOKEN);
      localStorage.removeItem(WebAuthStore.KEY_REFRESH_TOKEN);
    } catch {
      // Ignored
    }
  }
}
