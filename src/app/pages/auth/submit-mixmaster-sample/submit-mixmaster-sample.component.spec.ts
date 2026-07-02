import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { HttpEventType } from '@angular/common/http';

import { SubmitMixmasterSampleComponent } from './submit-mixmaster-sample.component';
import { AuthService } from '../../../services/auth.service';
import { environment } from '../../../../environments/environment';

const API_URL = `${environment.apiUrl}/api/auth/submit-mixmaster-sample`;

describe('SubmitMixmasterSampleComponent', () => {
  let component: SubmitMixmasterSampleComponent;
  let fixture: ComponentFixture<SubmitMixmasterSampleComponent>;
  let httpMock: HttpTestingController;

  const mockAuth = {
    getToken: vi.fn().mockReturnValue('test-jwt'),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    mockAuth.getToken.mockReturnValue('test-jwt');

    await TestBed.configureTestingModule({
      imports: [SubmitMixmasterSampleComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: mockAuth },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(SubmitMixmasterSampleComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => httpMock.verify());

  it('crée le composant', () => {
    expect(component).toBeTruthy();
  });

  // ── État initial ─────────────────────────────────────────────────────────────

  describe('état initial', () => {
    it('uploadProgress démarre à 0', () => {
      expect(component.uploadProgress()).toBe(0);
    });

    it('loading démarre à false', () => {
      expect(component.loading()).toBe(false);
    });

    it('success démarre à false', () => {
      expect(component.success()).toBe(false);
    });

    it('error démarre à null', () => {
      expect(component.error()).toBeNull();
    });
  });

  // ── Formulaire ───────────────────────────────────────────────────────────────

  describe('canSubmit()', () => {
    it('est false sans fichiers', () => {
      component.referencePrice.set(100);
      component.priceMin.set(40);
      component.bio.set('Expert en mixage');
      expect(component.canSubmit()).toBe(false);
    });

    it('est false sans bio', () => {
      component.referencePrice.set(100);
      component.priceMin.set(40);
      component.rawFile.set(new File([new Uint8Array(10)], 'raw.mp3'));
      component.processedFile.set(new File([new Uint8Array(10)], 'proc.mp3'));
      expect(component.canSubmit()).toBe(false);
    });

    it('est true avec tous les champs obligatoires', () => {
      component.referencePrice.set(100);
      component.priceMin.set(40);
      component.bio.set('Expert en mixage avec 10 ans d\'expérience');
      component.rawFile.set(new File([new Uint8Array(10)], 'raw.mp3'));
      component.processedFile.set(new File([new Uint8Array(10)], 'proc.mp3'));
      expect(component.canSubmit()).toBe(true);
    });
  });

  // ── onSubmit() ───────────────────────────────────────────────────────────────

  describe('onSubmit()', () => {
    const fillValidForm = () => {
      component.referencePrice.set(100);
      component.priceMin.set(40);
      component.bio.set('Ingénieur son professionnel — mixage et mastering');
      component.rawFile.set(new File([new Uint8Array(100)], 'raw.mp3', { type: 'audio/mpeg' }));
      component.processedFile.set(new File([new Uint8Array(100)], 'proc.mp3', { type: 'audio/mpeg' }));
    };

    it('ne lance pas la requête si le formulaire est incomplet', () => {
      component.onSubmit();
      httpMock.expectNone(API_URL);
    });

    it('passe loading=true au démarrage', () => {
      fillValidForm();
      component.onSubmit();
      expect(component.loading()).toBe(true);
      // consomme la requête en attente
      httpMock.expectOne(API_URL).flush({ success: true });
    });

    it('initialise uploadProgress à 0 avant l\'envoi', () => {
      fillValidForm();
      // Simule un état précédent
      component.uploadProgress.set(50);
      component.onSubmit();
      expect(component.uploadProgress()).toBe(0);
      httpMock.expectOne(API_URL).flush({ success: true });
    });

    it('envoie la requête avec Authorization header', () => {
      fillValidForm();
      component.onSubmit();
      const req = httpMock.expectOne(API_URL);
      expect(req.request.headers.get('Authorization')).toBe('Bearer test-jwt');
      req.flush({ success: true });
    });

    // ── Progression XHR ────────────────────────────────────────────────────────

    it('met à jour uploadProgress sur UploadProgress event', () => {
      fillValidForm();
      component.onSubmit();
      const req = httpMock.expectOne(API_URL);
      req.event({ type: HttpEventType.UploadProgress, loaded: 60, total: 100 } as any);
      expect(component.uploadProgress()).toBe(60);
      req.flush({ success: true });
    });

    it('calcule 0 % quand total est absent', () => {
      fillValidForm();
      component.onSubmit();
      const req = httpMock.expectOne(API_URL);
      req.event({ type: HttpEventType.UploadProgress, loaded: 40, total: undefined } as any);
      expect(component.uploadProgress()).toBe(0);
      req.flush({ success: true });
    });

    it('accumule plusieurs événements de progression', () => {
      fillValidForm();
      component.onSubmit();
      const req = httpMock.expectOne(API_URL);
      req.event({ type: HttpEventType.UploadProgress, loaded: 33, total: 100 } as any);
      expect(component.uploadProgress()).toBe(33);
      req.event({ type: HttpEventType.UploadProgress, loaded: 66, total: 100 } as any);
      expect(component.uploadProgress()).toBe(66);
      req.flush({ success: true });
    });

    // ── Réponse succès ─────────────────────────────────────────────────────────

    it('set success=true et progress=100 sur réponse success', () => {
      fillValidForm();
      component.onSubmit();
      const req = httpMock.expectOne(API_URL);
      req.flush({ success: true });
      expect(component.success()).toBe(true);
      expect(component.uploadProgress()).toBe(100);
      expect(component.loading()).toBe(false);
    });

    it('n\'affiche pas l\'erreur sur succès', () => {
      fillValidForm();
      component.onSubmit();
      httpMock.expectOne(API_URL).flush({ success: true });
      expect(component.error()).toBeNull();
    });

    // ── Réponse erreur ─────────────────────────────────────────────────────────

    it('set error et remet loading=false sur réponse d\'échec', () => {
      fillValidForm();
      component.onSubmit();
      httpMock.expectOne(API_URL).flush({
        success: false,
        feedback: { message: 'Fichier invalide' },
      });
      expect(component.success()).toBe(false);
      expect(component.error()).toBe('Fichier invalide');
      expect(component.loading()).toBe(false);
    });

    it('utilise message de fallback si feedback absent', () => {
      fillValidForm();
      component.onSubmit();
      httpMock.expectOne(API_URL).flush({ success: false });
      expect(component.error()).toBeTruthy();
    });

    // ── Erreur réseau ──────────────────────────────────────────────────────────

    it('remet uploadProgress=0 et loading=false sur erreur réseau', () => {
      fillValidForm();
      component.onSubmit();
      const req = httpMock.expectOne(API_URL);
      req.event({ type: HttpEventType.UploadProgress, loaded: 50, total: 100 } as any);
      expect(component.uploadProgress()).toBe(50);
      req.error(new ProgressEvent('error'));
      expect(component.uploadProgress()).toBe(0);
      expect(component.loading()).toBe(false);
      expect(component.error()).toBeTruthy();
    });
  });

  // ── Calcul des prix ──────────────────────────────────────────────────────────

  describe('calcul des prix', () => {
    it('minRequired est 35 % du prix de référence', () => {
      component.referencePrice.set(100);
      expect(component.minRequired()).toBe(35);
    });

    it('maxAllowed est 80 % du prix de référence', () => {
      component.referencePrice.set(100);
      expect(component.maxAllowed()).toBe(80);
    });

    it('priceError si prix minimum trop bas', () => {
      component.referencePrice.set(100);
      component.priceMin.set(20); // < 35 %
      expect(component.priceError()).toBeTruthy();
    });

    it('priceError si prix minimum trop haut', () => {
      component.referencePrice.set(100);
      component.priceMin.set(90); // > 80 %
      expect(component.priceError()).toBeTruthy();
    });

    it('pas d\'erreur prix pour une valeur valide', () => {
      component.referencePrice.set(100);
      component.priceMin.set(50); // 35 % ≤ 50 ≤ 80 %
      expect(component.priceError()).toBeNull();
    });
  });
});
