import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApiService, ApiError } from './api.service';

describe('ApiService', () => {
  let service: ApiService;
  let httpTesting: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ApiService);
    httpTesting = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpTesting.verify());

  it('should make GET requests to the correct URL', () => {
    service.get('/health').subscribe();
    const req = httpTesting.expectOne((r) => r.url.includes('/health'));
    expect(req.request.method).toBe('GET');
    req.flush({ status: 'available' });
  });

  it('should detect compliance-block errors on 503', () => {
    let caughtError: ApiError | null = null;
    service.get('/channels/test/summary').subscribe({
      error: (err: ApiError) => (caughtError = err),
    });

    const req = httpTesting.expectOne((r) => r.url.includes('/channels/test/summary'));
    req.flush(
      { detail: 'Env var: MICONTE_ANALYTICS_REAL_DATA_ENABLED=true' },
      { status: 503, statusText: 'Service Unavailable' },
    );

    expect(caughtError).toBeTruthy();
    expect(caughtError!.status).toBe(503);
    expect(caughtError!.isComplianceBlock).toBe(true);
  });

  it('should NOT flag non-compliance 503 errors', () => {
    let caughtError: ApiError | null = null;
    service.get('/health/db').subscribe({
      error: (err: ApiError) => (caughtError = err),
    });

    const req = httpTesting.expectOne((r) => r.url.includes('/health/db'));
    req.flush(
      { detail: 'Database unavailable' },
      { status: 503, statusText: 'Service Unavailable' },
    );

    expect(caughtError!.isComplianceBlock).toBe(false);
  });

  it('should make POST requests', () => {
    service.post('/channels/test/analysis/run').subscribe();
    const req = httpTesting.expectOne((r) => r.url.includes('/analysis/run'));
    expect(req.request.method).toBe('POST');
    req.flush({ analysis_run_id: 'abc' });
  });
});
