import { Injectable, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { ApiService } from './api.service';
import { environment } from '../../environments/environment';

export interface UserInfo {
  id: string;
  email: string;
  full_name: string | null;
  has_google_login: boolean;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly _currentUser = signal<UserInfo | null>(null);

  readonly currentUser = this._currentUser.asReadonly();

  constructor(private readonly api: ApiService) {}

  /**
   * Fetch the currently authenticated user from the backend.
   * Uses the HttpOnly session cookie — never reads token from JS.
   * Call this once at app startup to restore session state.
   */
  me(): Observable<UserInfo> {
    return this.api
      .get<UserInfo>('/auth/me')
      .pipe(tap((user) => this._currentUser.set(user)));
  }

  /**
   * Logout: invalidates the server-side session and clears the cookie.
   * The backend deletes the session record; the browser cookie is cleared
   * by the Set-Cookie response header.
   */
  logout(): Observable<{ detail: string }> {
    return this.api
      .post<{ detail: string }>('/auth/logout')
      .pipe(tap(() => this._currentUser.set(null)));
  }

  /**
   * Returns the backend URL that initiates Google OIDC login.
   * Angular must navigate the browser (not use HttpClient) to this URL
   * so the redirect to accounts.google.com happens as a full page load.
   */
  googleLoginUrl(): string {
    return `${environment.apiUrl}/auth/google/login`;
  }

  /**
   * Initiate Google login by navigating the browser to the backend endpoint.
   * This is a full page navigation — not an XHR call — so the browser follows
   * the redirect to Google and then back to the callback URI.
   */
  initiateGoogleLogin(): void {
    window.location.href = this.googleLoginUrl();
  }
}
