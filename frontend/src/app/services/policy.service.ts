import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface DocumentAcceptanceStatus {
  document_type: string;
  current_version: string;
  accepted_version: string | null;
  accepted_at: string | null;
  is_current: boolean;
}

export interface PolicyStatusResponse {
  current_versions: Record<string, string>;
  documents: DocumentAcceptanceStatus[];
  all_current_accepted: boolean;
}

@Injectable({ providedIn: 'root' })
export class PolicyService {
  private http = inject(HttpClient);
  private base = `${environment.apiUrl}/policy`;

  getVersions(): Observable<PolicyStatusResponse> {
    return this.http.get<PolicyStatusResponse>(`${this.base}/versions`);
  }

  acceptAll(): Observable<PolicyStatusResponse> {
    return this.http.post<PolicyStatusResponse>(`${this.base}/accept`, { accept_all: true });
  }
}
