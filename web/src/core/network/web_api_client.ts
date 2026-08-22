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
      throw new Error(await this.errorMessage(response));
    }
    return (await response.json()) as T;
  }

  /**
   * Extract a human-readable error message from a failed response.
   * FastAPI returns { detail: "..." } or { detail: [{ loc, msg }] } (422).
   */
  private async errorMessage(response: Response): Promise<string> {
    let detail: unknown = null;
    try {
      const body = await response.json();
      detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : null;
    } catch {
      detail = null;
    }

    if (typeof detail === 'string') {
      return detail;
    }
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => (item && typeof item === 'object' && 'msg' in item ? (item as { msg: string }).msg : null))
        .filter((m): m is string => typeof m === 'string');
      if (parts.length > 0) {
        return parts.join('; ');
      }
    }
    return `Request failed (${response.status} ${response.statusText})`;
  }

  public async post<T>(endpoint: string, body?: unknown, requireAuth = true): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers: this.getHeaders(requireAuth),
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      throw new Error(await this.errorMessage(response));
    }
    return (await response.json()) as T;
  }

  public async del<T>(endpoint: string, query?: Record<string, string>, requireAuth = true): Promise<T> {
    const qs = query ? `?${new URLSearchParams(query).toString()}` : '';
    const response = await fetch(`${this.baseUrl}${endpoint}${qs}`, {
      method: 'DELETE',
      headers: this.getHeaders(requireAuth),
    });

    if (!response.ok) {
      throw new Error(await this.errorMessage(response));
    }
    return (await response.json()) as T;
  }

  public async patch<T>(endpoint: string, body?: unknown, requireAuth = true): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'PATCH',
      headers: this.getHeaders(requireAuth),
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      throw new Error(await this.errorMessage(response));
    }
    return (await response.json()) as T;
  }

  // ---------------------------------------------------------------------------
  // Trusted device endpoints
  // ---------------------------------------------------------------------------

  public initiatePairing(deviceFingerprint: string, friendlyName?: string, devicePlatform?: string) {
    return this.post('/devices/pairing/initiate', {
      device_fingerprint: deviceFingerprint,
      friendly_name: friendlyName,
      device_platform: devicePlatform,
    });
  }

  public confirmPairing(pairingCode: string, password: string) {
    return this.post('/devices/pairing/confirm', {
      pairing_code: pairingCode,
      password,
    });
  }

  public listTrustedDevices() {
    return this.get('/devices/');
  }

  public revokeDevice(deviceId: string, password: string) {
    return this.del(`/devices/${deviceId}`, { password });
  }

  // ---------------------------------------------------------------------------
  // Assistance request / escalation endpoints
  // ---------------------------------------------------------------------------

  public requestHelp(sessionId: string, helperUserId: string, helperDeviceFingerprint: string) {
    return this.post(`/sessions/${sessionId}/assistance/request`, {
      helper_user_id: helperUserId,
      helper_device_fingerprint: helperDeviceFingerprint,
    });
  }

  public respondToHelpRequest(sessionId: string, requestId: string, accept: boolean, helperDeviceFingerprint?: string) {
    return this.post(`/sessions/${sessionId}/assistance/request/${requestId}/respond`, {
      accept,
      helper_device_fingerprint: helperDeviceFingerprint,
    });
  }

  public requestEscalation(sessionId: string, targetCapabilities: string[]) {
    return this.post(`/sessions/${sessionId}/assistance/escalation`, {
      target_capabilities: targetCapabilities,
    });
  }

  public getEscalation(sessionId: string, escalationId: string) {
    return this.get(`/sessions/${sessionId}/assistance/escalation/${escalationId}`);
  }

  public respondToEscalation(sessionId: string, escalationId: string, accept: boolean, acceptDisclaimer: boolean) {
    return this.post(`/sessions/${sessionId}/assistance/escalation/${escalationId}/respond`, {
      accept,
      accept_disclaimer: acceptDisclaimer,
    });
  }
}
