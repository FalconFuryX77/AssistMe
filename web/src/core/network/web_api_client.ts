/**
 * Web API Client for Browser Applications.
 * Wrapper over Fetch API with automatic JWT Bearer header injection and JSON parsing.
 */

import { WebAuthStore } from '../security/web_auth_store';

export class WebApiClient {
  private readonly baseUrl: string;
  private readonly authStore: WebAuthStore;

  constructor(baseUrl: string, authStore: WebAuthStore) {
    this.baseUrl = baseUrl;
    this.authStore = authStore;
  }

  private getHeaders(requireAuth = true): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    if (requireAuth) {
      const token = this.authStore.getAccessToken();
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
    }
    return headers;
  }

  public async get<T>(endpoint: string, requireAuth = true): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'GET',
      headers: this.getHeaders(requireAuth),
    });

    if (!response.ok) {
      throw new Error(`API Error ${response.status}: ${response.statusText}`);
    }
    return (await response.json()) as T;
  }

  public async post<T>(endpoint: string, body?: unknown, requireAuth = true): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers: this.getHeaders(requireAuth),
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      throw new Error(`API Error ${response.status}: ${response.statusText}`);
    }
    return (await response.json()) as T;
  }
}
