import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { vi } from 'vitest';

import { NavbarComponent as Navbar } from './navbar.component';
import { AuthService } from '../../services/auth.service';

describe('Navbar', () => {
  let component: Navbar;
  let fixture: ComponentFixture<Navbar>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Navbar],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(Navbar);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
  it('animates login and logout in sequence without delaying authentication', async () => {
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const auth = TestBed.inject(AuthService);
    auth.updateCurrentUser({ id: 1234, username: 'Motion' });
    fixture.detectChanges();
    expect(auth.isLoggedIn()).toBe(true);
    expect(component.isLoggedIn()).toBe(false);
    expect(component.authMotion()).toBe('out');
    expect(fixture.nativeElement.querySelector('#navbarNav').hasAttribute('inert')).toBe(true);

    await new Promise(resolve => setTimeout(resolve, 200));
    fixture.detectChanges();
    expect(component.authMotion()).toBe('in');
    expect(component.username()).toBe('Motion');

    await new Promise(resolve => setTimeout(resolve, 260));
    fixture.detectChanges();
    expect(component.authMotion()).toBe('idle');
    expect(fixture.nativeElement.querySelector('#navbarNav').hasAttribute('inert')).toBe(false);

    auth.updateCurrentUser({ username: 'Updated' });
    fixture.detectChanges();
    expect(component.username()).toBe('Updated');
    expect(component.authMotion()).toBe('idle');

    auth.silentLogout();
    fixture.detectChanges();
    expect(auth.isLoggedIn()).toBe(false);
    expect(component.isLoggedIn()).toBe(true);
    expect(component.authMotion()).toBe('out');
    await new Promise(resolve => setTimeout(resolve, 200));
    fixture.detectChanges();
    expect(component.isLoggedIn()).toBe(false);
    expect(component.authMotion()).toBe('in');
  });

  it('updates immediately when reduced motion is requested', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    try {
      TestBed.inject(AuthService).updateCurrentUser({ id: 1234, username: 'Motion' });
      fixture.detectChanges();
      expect(component.isLoggedIn()).toBe(true);
      expect(component.authMotion()).toBe('idle');
    } finally {
      sessionStorage.removeItem('user');
      vi.unstubAllGlobals();
    }
  });
});
