import { TestBed } from '@angular/core/testing';
import { ComplianceNoticeComponent } from './compliance-notice';

describe('ComplianceNoticeComponent', () => {
  it('should render default message', async () => {
    await TestBed.configureTestingModule({
      imports: [ComplianceNoticeComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(ComplianceNoticeComponent);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.compliance-notice')).toBeTruthy();
    expect(el.textContent).toContain('Funcionalidad no disponible');
    expect(el.textContent).toContain('verificación de la aplicación OAuth');
  });
});
