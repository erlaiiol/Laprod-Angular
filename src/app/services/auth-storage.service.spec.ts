import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AuthStorageService, AUTH_NATIVE_PLATFORM, AUTH_SECURE_STORAGE } from './auth-storage.service';

const SecureStorage = { get: vi.fn(), set: vi.fn(), remove: vi.fn() };

const session = { access_token: 'access', refresh_token: 'refresh', user: '{"id":1}' };

describe('native auth storage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    TestBed.configureTestingModule({ providers: [
      { provide: AUTH_NATIVE_PLATFORM, useValue: true },
      { provide: AUTH_SECURE_STORAGE, useValue: SecureStorage },
    ] });
    vi.mocked(SecureStorage.get).mockResolvedValue(null);
    vi.mocked(SecureStorage.set).mockResolvedValue(undefined);
    vi.mocked(SecureStorage.remove).mockResolvedValue(true);
    localStorage.clear(); sessionStorage.clear();
  });
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });

  it('restores credentials even when the WebView storage has been emptied', async () => {
    vi.mocked(SecureStorage.get).mockResolvedValue(session);
    const storage = TestBed.inject(AuthStorageService);
    await storage.initialize();
    expect(storage.persistent.getItem('refresh_token')).toBe('refresh');
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('migrates existing persistent sessions before clearing the WebView copy', async () => {
    for (const [key, value] of Object.entries(session)) localStorage.setItem(key, value);
    const storage = TestBed.inject(AuthStorageService);
    await storage.initialize();
    expect(SecureStorage.set).toHaveBeenCalledWith('net.laprod.auth.v1', session, false, false);
    expect(storage.persistent.getItem('access_token')).toBe('access');
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('preserves the legacy copy if migration fails', async () => {
    for (const [key, value] of Object.entries(session)) localStorage.setItem(key, value);
    vi.mocked(SecureStorage.set).mockRejectedValue(new Error('locked'));
    await expect(TestBed.inject(AuthStorageService).initialize()).rejects.toThrow('locked');
    expect(localStorage.getItem('refresh_token')).toBe('refresh');
  });

  it('keeps short sessions in memory without persisting their credentials', async () => {
    const storage = TestBed.inject(AuthStorageService);
    await storage.initialize();
    storage.session.setItem('refresh_token', 'temporary');
    await storage.flush();
    expect(SecureStorage.set).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('refresh_token')).toBeNull();
  });

  it('allows a fresh login when the saved record is incomplete', async () => {
    vi.mocked(SecureStorage.get).mockResolvedValue({ access_token: 'orphan' });
    const storage = TestBed.inject(AuthStorageService);
    await storage.initialize();
    expect(storage.persistent.getItem('access_token')).toBeNull();
    expect(SecureStorage.remove).toHaveBeenCalledWith('net.laprod.auth.v1', false);
  });

  it('does not erase credentials when the OS temporarily refuses access', async () => {
    vi.mocked(SecureStorage.get).mockRejectedValue(new Error('device locked'));
    await expect(TestBed.inject(AuthStorageService).initialize()).rejects.toThrow('device locked');
    expect(SecureStorage.remove).not.toHaveBeenCalled();
  });

  it('serializes writes so logout removes a pending saved session', async () => {
    const storage = TestBed.inject(AuthStorageService);
    await storage.initialize();
    let release!: () => void;
    let started!: () => void;
    const writing = new Promise<void>(resolve => { started = resolve; });
    vi.mocked(SecureStorage.set).mockImplementationOnce(() => {
      started();
      return new Promise<void>(resolve => { release = resolve; });
    });
    storage.persistent.setItem('refresh_token', 'refresh');
    await writing;
    storage.persistent.removeItem('refresh_token');
    release();
    await storage.flush();
    expect(SecureStorage.remove).toHaveBeenLastCalledWith('net.laprod.auth.v1', false);
    expect(storage.persistent.getItem('refresh_token')).toBeNull();
  });
});
