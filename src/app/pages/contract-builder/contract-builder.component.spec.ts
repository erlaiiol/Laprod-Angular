import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { By } from '@angular/platform-browser';
import { of } from 'rxjs';
import { vi } from 'vitest';

import { ContractBuilderComponent } from './contract-builder.component';
import { ContractBuilderService } from '../../services/contract-builder.service';
import { RosterService } from '../../services/roster.service';
import { AuthService } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';

// ── Setup ─────────────────────────────────────────────────────────────────────

function setup(auth: { isLoggedIn: boolean; isPro: boolean; canManage?: boolean }) {
  const svc = {
    listContracts:  vi.fn().mockReturnValue(of({ success: true, data: { contracts: [] } })),
    createContract: vi.fn().mockReturnValue(of({ success: true, data: { contract: { id: 42 } } })),
  };
  const rosterSvc = {
    attachContract: vi.fn().mockReturnValue(of({ success: true, data: {} })),
  };
  const authSvc = {
    isLoggedIn:              vi.fn().mockReturnValue(auth.isLoggedIn),
    isPro:                   vi.fn().mockReturnValue(auth.isPro),
    canUseManagementContract: vi.fn().mockReturnValue(auth.canManage ?? false),
  };
  const toastSvc = { showToast: vi.fn() };

  TestBed.configureTestingModule({
    imports: [ContractBuilderComponent],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([{ path: '**', component: ContractBuilderComponent }]),
      { provide: ContractBuilderService, useValue: svc },
      { provide: RosterService, useValue: rosterSvc },
      { provide: AuthService, useValue: authSvc },
      { provide: ToastService, useValue: toastSvc },
    ],
  });

  const fixture = TestBed.createComponent(ContractBuilderComponent);
  fixture.detectChanges();
  return { fixture, component: fixture.componentInstance, svc, rosterSvc, toastSvc };
}

function text(fixture: ComponentFixture<ContractBuilderComponent>, selector: string): string | null {
  const el = fixture.debugElement.query(By.css(selector));
  return el ? (el.nativeElement.textContent ?? '').trim() : null;
}

// ── Suite ─────────────────────────────────────────────────────────────────────

describe('ContractBuilderComponent', () => {

  it('should create', () => {
    const { component } = setup({ isLoggedIn: false, isPro: false });
    expect(component).toBeTruthy();
  });

  describe('invité (non connecté)', () => {
    it('shows the guest banner and the demo link, and does not call listContracts', () => {
      const { fixture, svc } = setup({ isLoggedIn: false, isPro: false });
      expect(fixture.debugElement.query(By.css('.cb-guest-banner'))).toBeTruthy();
      expect(text(fixture, '.cb-guest-banner')).toContain('Connectez-vous');
      expect(fixture.debugElement.query(By.css('.cb-demo-link'))).toBeTruthy();
      expect(svc.listContracts).not.toHaveBeenCalled();
    });

    it('leaves the type-choice cards explorable (locked badge, not disabled), shows a login CTA instead of Create', () => {
      const { fixture } = setup({ isLoggedIn: false, isPro: false });
      const typeCard = fixture.debugElement.query(By.css('.cb-type-card'));
      expect(typeCard.nativeElement.disabled).toBe(false);
      expect(typeCard.nativeElement.classList).toContain('locked');
      expect(fixture.debugElement.query(By.css('.cb-login-btn'))).toBeTruthy();
      expect(fixture.debugElement.query(By.css('button.btn-primary'))).toBeFalsy();
    });

    it('shows a guest message instead of the contracts list', () => {
      const { fixture } = setup({ isLoggedIn: false, isPro: false });
      expect(fixture.debugElement.query(By.css('.cb-guest-list-msg'))).toBeTruthy();
    });
  });

  describe('connecté, non-Pro', () => {
    it('shows the Premium upsell banner (not the guest banner) and the demo link', () => {
      const { fixture, svc } = setup({ isLoggedIn: true, isPro: false });
      expect(text(fixture, '.cb-guest-banner')).toContain('réservée au plan Pro');
      expect(fixture.debugElement.query(By.css('.cb-demo-link'))).toBeTruthy();
      expect(svc.listContracts).toHaveBeenCalled();
    });

    it('disables creation and shows a Premium CTA instead of the Create button', () => {
      const { fixture } = setup({ isLoggedIn: true, isPro: false });
      const typeCard = fixture.debugElement.query(By.css('.cb-type-card'));
      expect(typeCard.nativeElement.disabled).toBe(false);
      expect(typeCard.nativeElement.classList).toContain('locked');
      expect(text(fixture, '.cb-login-btn')).toContain('Pro uniquement');
      expect(fixture.debugElement.query(By.css('button.btn-primary'))).toBeFalsy();
    });
  });

  describe('connecté, Premium sans Pro (management uniquement)', () => {
    it('unlocks only the management card and allows creating a management contract', () => {
      const { fixture, component, svc } = setup({ isLoggedIn: true, isPro: false, canManage: true });
      component.newType.set('management');
      fixture.detectChanges();

      expect(fixture.debugElement.query(By.css('.cb-login-btn'))).toBeFalsy();

      component.newTitle.set('Mandat de test');
      fixture.detectChanges();
      const createBtn = fixture.debugElement.query(By.css('button.btn-primary'));
      expect(createBtn).toBeTruthy();
      createBtn.nativeElement.click();

      expect(svc.createContract).toHaveBeenCalledWith('Mandat de test', 'management');
    });
  });

  describe('connecté, Pro', () => {
    it('shows no banner and no demo link, loads the contract list', () => {
      const { fixture, svc } = setup({ isLoggedIn: true, isPro: true });
      expect(fixture.debugElement.query(By.css('.cb-guest-banner'))).toBeFalsy();
      expect(fixture.debugElement.query(By.css('.cb-demo-link'))).toBeFalsy();
      expect(svc.listContracts).toHaveBeenCalled();
    });

    it('enables the creation form and calls createContract() on submit', () => {
      const { fixture, component, svc } = setup({ isLoggedIn: true, isPro: true });
      const typeCard = fixture.debugElement.query(By.css('.cb-type-card'));
      expect(typeCard.nativeElement.disabled).toBe(false);

      component.newTitle.set('Mon titre');
      fixture.detectChanges();
      const createBtn = fixture.debugElement.query(By.css('button.btn-primary'));
      expect(createBtn).toBeTruthy();
      createBtn.nativeElement.click();

      expect(svc.createContract).toHaveBeenCalledWith('Mon titre', 'exploitation');
    });
  });

  describe('typeLabel() / placeholderForType()', () => {
    it('resolves the label for a known contract type', () => {
      const { component } = setup({ isLoggedIn: true, isPro: true });
      expect(component.typeLabel('performance')).toContain('représentation');
    });

    it('returns an empty string for an unknown type', () => {
      const { component } = setup({ isLoggedIn: true, isPro: true });
      expect(component.typeLabel('unknown' as any)).toBe('');
    });
  });
});
