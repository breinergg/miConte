import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface ApiError {
  status: number;
  message: string;
  isComplianceBlock: boolean;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  readonly baseUrl = environment.apiUrl;

  constructor(readonly http: HttpClient) {}

  get<T>(path: string, params?: Record<string, string | number>): Observable<T> {
    return this.http
      .get<T>(`${this.baseUrl}${path}`, {
        params: params as Record<string, string>,
        withCredentials: true,
      })
      .pipe(catchError((err) => this.handleError(err)));
  }

  post<T>(path: string, body?: unknown): Observable<T> {
    return this.http
      .post<T>(`${this.baseUrl}${path}`, body ?? {}, { withCredentials: true })
      .pipe(catchError((err) => this.handleError(err)));
  }

  private handleError(error: HttpErrorResponse): Observable<never> {
    const apiError: ApiError = {
      status: error.status,
      message: error.error?.detail ?? error.message ?? 'Error de conexión',
      isComplianceBlock: error.status === 503 && !!error.error?.detail?.includes('MICONTE_ANALYTICS_REAL_DATA_ENABLED'),
    };
    return throwError(() => apiError);
  }
}
