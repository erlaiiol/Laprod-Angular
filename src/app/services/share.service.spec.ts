import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { ShareService } from './share.service';
import { ToastService } from './toast.service';

describe('ShareService', () => {
  let service: ShareService;
  const showToast = vi.fn();

  beforeEach(() => {
    showToast.mockReset();
    // JSDOM ne définit pas navigator.share — on le crée configurable
    if (!Object.getOwnPropertyDescriptor(navigator, 'share')) {
      Object.defineProperty(navigator, 'share', {
        value: vi.fn().mockResolvedValue(undefined),
        configurable: true,
        writable: true,
      });
    }
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      configurable: true,
      writable: true,
    });

    TestBed.configureTestingModule({
      providers: [
        ShareService,
        { provide: ToastService, useValue: { showToast } },
      ],
    });
    service = TestBed.inject(ShareService);
  });

  afterEach(() => vi.restoreAllMocks());

  it('should be created', () => expect(service).toBeTruthy());

  it('share() appelle navigator.share avec l\'url absolue et le titre', async () => {
    (navigator.share as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    await service.share('https://laprod.fr/track/1', 'Mon beat');
    expect(navigator.share).toHaveBeenCalledWith({ title: 'Mon beat', url: 'https://laprod.fr/track/1' });
  });

  it('share() préfixe l\'url relative avec window.location.origin', async () => {
    (navigator.share as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    await service.share('/track/1');
    const call = (navigator.share as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.url).toContain('/track/1');
    expect(call.url).toMatch(/^http/);
  });

  it('share() ne copie PAS dans le clipboard si navigator.share lance AbortError', async () => {
    const abortError = Object.assign(new Error('abort'), { name: 'AbortError' });
    (navigator.share as ReturnType<typeof vi.fn>).mockRejectedValue(abortError);

    await service.share('https://laprod.fr/track/1');
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled();
  });

  it('share() copie dans le clipboard si navigator.share lance une erreur non-AbortError', async () => {
    (navigator.share as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('not supported'));

    await service.share('https://laprod.fr/track/1');
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://laprod.fr/track/1');
    expect(showToast).toHaveBeenCalledWith(expect.objectContaining({ level: 'success' }));
  });

  it('affiche un toast d\'erreur si le clipboard échoue', async () => {
    (navigator.share as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('err'));
    (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('denied'));

    await service.share('https://laprod.fr');
    expect(showToast).toHaveBeenCalledWith(expect.objectContaining({ level: 'error' }));
  });
});
