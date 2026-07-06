import { TestBed } from '@angular/core/testing';
import { ErrorService } from './error.service';

describe('ErrorService', () => {
  let service: ErrorService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(ErrorService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('current() vaut null au démarrage', () => {
    expect(service.current()).toBeNull();
  });

  it('set() définit une erreur', () => {
    service.set({ code: 403 });
    expect(service.current()?.code).toBe(403);
  });

  it('set() accepte un context optionnel', () => {
    service.set({ code: 403, context: 'admin' });
    expect(service.current()?.context).toBe('admin');
  });

  it('clear() remet current à null', () => {
    service.set({ code: 500 });
    service.clear();
    expect(service.current()).toBeNull();
  });
});
