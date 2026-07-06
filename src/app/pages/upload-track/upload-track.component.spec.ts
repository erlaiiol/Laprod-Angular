import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Subject, of } from 'rxjs';
import { HttpEventType } from '@angular/common/http';
import { signal } from '@angular/core';

import { UploadTrackComponent } from './upload-track.component';
import { CudTrackService } from '../../services/cud-track.service';
import { UploadStatusService } from '../../services/upload-status.service';
import { AuthService } from '../../services/auth.service';
import { TagsService } from '../../services/tags.service';
import { PlaylistService } from '../../services/playlist.service';
import { SimilarArtistsService } from '../../services/similar-artists.service';

// jsdom ne fournit pas URL.createObjectURL
beforeAll(() => {
  if (!URL.createObjectURL) {
    (URL as any).createObjectURL = vi.fn().mockReturnValue('blob:mock');
  }
});

describe('UploadTrackComponent', () => {
  let component: UploadTrackComponent;
  let fixture: ComponentFixture<UploadTrackComponent>;
  let postSubject: Subject<any>;

  const mockUploadStatus = {
    openForUpload: vi.fn(),
    setUploadProgress: vi.fn(),
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
    status: signal<any>(null),
    progress: signal(0),
    title: signal<string | null>(null),
    imageUrl: signal<string | null>(null),
    trackId: signal<string | null>(null),
    errorMessage: signal<string | null>(null),
  };

  const mockAuth = {
    isLoggedIn: vi.fn().mockReturnValue(true),
    isBeatmaker: vi.fn().mockReturnValue(true),
    isPremium: vi.fn().mockReturnValue(false),
    me: vi.fn().mockReturnValue(of({})),
    getToken: vi.fn().mockReturnValue('tok'),
    refreshIfExpiringSoon: vi.fn().mockReturnValue(of(undefined)),
    currentUser: signal<any>(null),
    isPremiumActive: false,
  };

  const mockCudTrack = { postTrack: vi.fn() };
  const mockTags = { getTags: vi.fn() };
  const mockPlaylist = { getMyPlaylists: vi.fn() };
  const mockSimilarArtists = { getSimilarArtists: vi.fn() };

  beforeEach(async () => {
    postSubject = new Subject();
    vi.clearAllMocks();

    mockCudTrack.postTrack.mockReturnValue(postSubject.asObservable());
    mockAuth.isLoggedIn.mockReturnValue(true);
    mockAuth.isBeatmaker.mockReturnValue(true);
    mockAuth.isPremium.mockReturnValue(false);
    mockAuth.me.mockReturnValue(of({}));
    mockTags.getTags.mockReturnValue(of({ success: true, data: { tags: [], styles: [] } }));
    mockPlaylist.getMyPlaylists.mockReturnValue(of({ data: [] }));
    mockSimilarArtists.getSimilarArtists.mockReturnValue(of({ success: true, data: { scenes: [] } }));

    await TestBed.configureTestingModule({
      imports: [UploadTrackComponent],
      providers: [
        provideRouter([]),
        { provide: CudTrackService,        useValue: mockCudTrack },
        { provide: UploadStatusService,    useValue: mockUploadStatus },
        { provide: AuthService,            useValue: mockAuth },
        { provide: TagsService,            useValue: mockTags },
        { provide: PlaylistService,        useValue: mockPlaylist },
        { provide: SimilarArtistsService,  useValue: mockSimilarArtists },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(UploadTrackComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('crée le composant', () => {
    expect(component).toBeTruthy();
  });

  it('redirige vers /login si non authentifié', async () => {
    mockAuth.isLoggedIn.mockReturnValue(false);
    const routerSpy = vi.spyOn((component as any).router, 'navigate').mockResolvedValue(true);
    component.ngOnInit();
    expect(routerSpy).toHaveBeenCalledWith(['/login']);
  });

  // ── Validation formulaire ────────────────────────────────────────────────────

  describe('validation du formulaire', () => {
    it('canSubmit est false sans titre', () => {
      component.bpm.set(120);
      component.key.set('C');
      component.style.set('Trap');
      component.fileMp3.set(new File([new Uint8Array(10)], 'b.mp3'));
      expect(component.canSubmit()).toBe(false);
    });

    it('canSubmit est false sans fichier audio', () => {
      component.title.set('Beat');
      component.bpm.set(120);
      component.key.set('C');
      component.style.set('Trap');
      expect(component.canSubmit()).toBe(false);
    });

    it('canSubmit est true avec les champs obligatoires', () => {
      component.title.set('Beat');
      component.bpm.set(120);
      component.key.set('C');
      component.style.set('Trap');
      component.fileMp3.set(new File([new Uint8Array(10)], 'b.mp3'));
      expect(component.canSubmit()).toBe(true);
    });
  });

  // ── onSubmit() ───────────────────────────────────────────────────────────────

  describe('onSubmit()', () => {
    const fillForm = () => {
      component.title.set('Mon Beat');
      component.bpm.set(120);
      component.key.set('C major');
      component.style.set('Trap');
      component.fileMp3.set(new File([new Uint8Array(100)], 'beat.mp3', { type: 'audio/mpeg' }));
    };

    it('ne lance pas l\'upload si le formulaire est invalide', () => {
      component.onSubmit();
      expect(mockCudTrack.postTrack).not.toHaveBeenCalled();
      expect(mockUploadStatus.openForUpload).not.toHaveBeenCalled();
    });

    it('appelle openForUpload() AVANT de lancer la requête HTTP', () => {
      fillForm();
      const callOrder: string[] = [];
      mockUploadStatus.openForUpload.mockImplementation(() => callOrder.push('open'));
      mockCudTrack.postTrack.mockImplementation(() => { callOrder.push('http'); return postSubject.asObservable(); });

      component.onSubmit();

      expect(callOrder).toEqual(['open', 'http']);
    });

    it('appelle openForUpload avec le titre du formulaire', () => {
      fillForm();
      component.onSubmit();
      expect(mockUploadStatus.openForUpload).toHaveBeenCalledWith('Mon Beat', null);
    });

    it('passe loading=true pendant l\'upload', () => {
      fillForm();
      component.onSubmit();
      expect(component.loading()).toBe(true);
    });

    it('route les événements UploadProgress vers setUploadProgress()', () => {
      fillForm();
      component.onSubmit();
      postSubject.next({ type: HttpEventType.UploadProgress, loaded: 60, total: 100 });
      expect(mockUploadStatus.setUploadProgress).toHaveBeenCalledWith(60);
    });

    it('calcule 0 % quand total est absent dans UploadProgress', () => {
      fillForm();
      component.onSubmit();
      postSubject.next({ type: HttpEventType.UploadProgress, loaded: 40, total: undefined });
      expect(mockUploadStatus.setUploadProgress).toHaveBeenCalledWith(0);
    });

    it('appelle startPolling() avec le job_id sur réponse success', () => {
      fillForm();
      component.onSubmit();
      postSubject.next({
        type: HttpEventType.Response,
        body: { success: true, data: { job_id: 'job-123', title: 'Mon Beat', image_url: null } },
      });
      expect(mockUploadStatus.startPolling).toHaveBeenCalledWith('job-123');
    });

    it('appelle stopPolling() et set error sur réponse d\'échec', () => {
      fillForm();
      component.onSubmit();
      postSubject.next({
        type: HttpEventType.Response,
        body: { success: false, feedback: { level: 'error', message: 'Token épuisé' } },
      });
      expect(mockUploadStatus.stopPolling).toHaveBeenCalled();
      expect(component.error()).toBe('Token épuisé');
      expect(component.loading()).toBe(false);
    });

    it('appelle stopPolling() sur erreur réseau', () => {
      fillForm();
      component.onSubmit();
      postSubject.error({ error: { feedback: { message: 'Réseau indisponible' } } });
      expect(mockUploadStatus.stopPolling).toHaveBeenCalled();
      expect(component.error()).toBe('Réseau indisponible');
      expect(component.loading()).toBe(false);
    });

    it('plusieurs événements UploadProgress mettent à jour la progression', () => {
      fillForm();
      component.onSubmit();
      postSubject.next({ type: HttpEventType.UploadProgress, loaded: 25, total: 100 });
      expect(mockUploadStatus.setUploadProgress).toHaveBeenCalledWith(25);
      postSubject.next({ type: HttpEventType.UploadProgress, loaded: 75, total: 100 });
      expect(mockUploadStatus.setUploadProgress).toHaveBeenCalledWith(75);
      expect(mockUploadStatus.setUploadProgress).toHaveBeenCalledTimes(2);
    });
  });
});
