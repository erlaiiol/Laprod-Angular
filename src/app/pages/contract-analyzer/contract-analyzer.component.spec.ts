import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { By } from '@angular/platform-browser';
import { of } from 'rxjs';
import { vi } from 'vitest';

import { ContractAnalyzerComponent } from './contract-analyzer.component';
import { ContractAnalyzerService } from '../../services/contract-analyzer.service';
import { AuthService } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';

// ── Setup ─────────────────────────────────────────────────────────────────────

const FAKE_ANALYSIS = {
  contract_type: 'Contrat de licence',
  overall_score: 70,
  risk_level: 'modéré',
  summary: 'Résumé de test.',
  detected_parties: [],
  critical_articles: [],
  sections: [],
  missing_clauses: [],
  positive_points: [],
  career_advice: '',
  negotiation_checklist: [],
};

function setup(auth: { isLoggedIn: boolean; isPremium: boolean }) {
  const svc = {
    analyzeContract: vi.fn().mockReturnValue(of({ success: true, data: { analysis: FAKE_ANALYSIS } })),
  };
  const authSvc = {
    isLoggedIn: vi.fn().mockReturnValue(auth.isLoggedIn),
    isPremium:  vi.fn().mockReturnValue(auth.isPremium),
  };
  const toastSvc = { showToast: vi.fn() };

  TestBed.configureTestingModule({
    imports: [ContractAnalyzerComponent],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([{ path: '**', component: ContractAnalyzerComponent }]),
      { provide: ContractAnalyzerService, useValue: svc },
      { provide: AuthService, useValue: authSvc },
      { provide: ToastService, useValue: toastSvc },
    ],
  });

  const fixture = TestBed.createComponent(ContractAnalyzerComponent);
  fixture.detectChanges();
  return { fixture, component: fixture.componentInstance, svc };
}

function text(fixture: ComponentFixture<ContractAnalyzerComponent>, selector: string): string | null {
  const el = fixture.debugElement.query(By.css(selector));
  return el ? (el.nativeElement.textContent ?? '').trim() : null;
}

// ── Suite ─────────────────────────────────────────────────────────────────────

describe('ContractAnalyzerComponent', () => {

  it('should create', () => {
    const { component } = setup({ isLoggedIn: false, isPremium: false });
    expect(component).toBeTruthy();
  });

  describe('invité (non connecté)', () => {
    it('shows the guest drop-zone with a login CTA, not the functional drop-zone', () => {
      const { fixture } = setup({ isLoggedIn: false, isPremium: false });
      expect(fixture.debugElement.query(By.css('.ca-drop-zone--guest'))).toBeTruthy();
      expect(fixture.debugElement.query(By.css('label.btn-upload input[type="file"]'))).toBeFalsy();
      expect(text(fixture, '.ca-drop-zone--guest a.btn-upload')).toContain('Se connecter');
    });

    it('shows the demo analysis with a "connectez-vous" call to action', () => {
      const { fixture } = setup({ isLoggedIn: false, isPremium: false });
      expect(fixture.debugElement.query(By.css('.ca-demo-banner'))).toBeTruthy();
      expect(text(fixture, '.ca-demo-banner')).toContain('connectez-vous');
      // Le contenu de l'exemple (score, résumé) doit être affiché en clair
      expect(fixture.debugElement.query(By.css('.ca-score-card'))).toBeTruthy();
    });
  });

  describe('connecté, non-premium', () => {
    it('shows a Premium CTA drop-zone instead of the functional one', () => {
      const { fixture } = setup({ isLoggedIn: true, isPremium: false });
      const zones = fixture.debugElement.queryAll(By.css('.ca-drop-zone'));
      expect(zones.length).toBe(1);
      expect(zones[0].nativeElement.classList).toContain('ca-drop-zone--guest');
      expect(text(fixture, '.ca-drop-zone a.btn-upload')).toContain('Passer Premium');
      expect(fixture.debugElement.query(By.css('label.btn-upload input[type="file"]'))).toBeFalsy();
    });

    it('still shows the demo analysis, with a "passez Premium" call to action', () => {
      const { fixture } = setup({ isLoggedIn: true, isPremium: false });
      expect(fixture.debugElement.query(By.css('.ca-demo-banner'))).toBeTruthy();
      expect(text(fixture, '.ca-demo-banner')).toContain('passez Premium');
    });
  });

  describe('connecté, premium', () => {
    it('shows the functional drop-zone and no demo', () => {
      const { fixture, svc } = setup({ isLoggedIn: true, isPremium: true });
      expect(fixture.debugElement.query(By.css('.ca-drop-zone--guest'))).toBeFalsy();
      expect(fixture.debugElement.query(By.css('label.btn-upload input[type="file"]'))).toBeTruthy();
      expect(fixture.debugElement.query(By.css('.ca-demo-banner'))).toBeFalsy();
      expect(svc.analyzeContract).not.toHaveBeenCalled();
    });

    it('calls analyzeContract() and switches to the result phase on file drop', () => {
      const { fixture, component, svc } = setup({ isLoggedIn: true, isPremium: true });
      const file = new File(['%PDF-1.4'], 'contrat.pdf', { type: 'application/pdf' });
      component.handleFile(file);
      fixture.detectChanges();

      expect(svc.analyzeContract).toHaveBeenCalledWith(file);
      expect(component.phase()).toBe('result');
    });

    it('rejects non-PDF files without calling the service', () => {
      const { component, svc } = setup({ isLoggedIn: true, isPremium: true });
      const file = new File(['hello'], 'contrat.txt', { type: 'text/plain' });
      component.handleFile(file);

      expect(component.fileError()).toContain('PDF');
      expect(svc.analyzeContract).not.toHaveBeenCalled();
    });
  });
});
