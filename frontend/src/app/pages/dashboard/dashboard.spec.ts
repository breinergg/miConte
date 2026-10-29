import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { DashboardComponent } from './dashboard';

describe('DashboardComponent', () => {
  let httpTesting: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    httpTesting = TestBed.inject(HttpTestingController);
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should show no-channel state when API returns empty list', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    const req = httpTesting.expectOne((r) => r.url.includes('/sync/channels'));
    req.flush([]);
    fixture.detectChanges();
    await fixture.whenStable();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Sin canal conectado');
  });

  it('should show compliance-blocked state on 503', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    fixture.detectChanges();

    const channelsReq = httpTesting.expectOne((r) => r.url.includes('/sync/channels'));
    channelsReq.flush([{ channel_id: 'UC123', title: 'Test', is_oauth_connected: true }]);
    fixture.detectChanges();

    const summaryReq = httpTesting.expectOne((r) => r.url.includes('/channels/UC123/summary'));
    summaryReq.flush(
      { detail: 'MICONTE_ANALYTICS_REAL_DATA_ENABLED must be set' },
      { status: 503, statusText: 'Service Unavailable' },
    );
    fixture.detectChanges();
    await fixture.whenStable();

    expect(fixture.componentInstance.state()).toBe('compliance-blocked');
  });

  afterEach(() => httpTesting.verify());
});
