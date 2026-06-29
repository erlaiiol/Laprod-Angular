import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { AddToPlaylistModalComponent } from './add-to-playlist-modal.component';
import { PlaylistService, Playlist } from '../../services/playlist.service';
import { AuthService } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';

const makePl = (id: number, title = `Playlist ${id}`): Playlist => ({
  id, title, image_file: null, track_count: 2,
  beatmaker_username: 'bm', created_at: null,
});

describe('AddToPlaylistModalComponent', () => {
  let fixture: ComponentFixture<AddToPlaylistModalComponent>;
  let component: AddToPlaylistModalComponent;

  const playlistSvc = {
    getMyPlaylists: vi.fn(),
    getContaining:  vi.fn(),
    addTrack:       vi.fn(),
    removeTrack:    vi.fn(),
    createPlaylist: vi.fn(),
  };
  const authSvc  = { currentUser: vi.fn() };
  const toastSvc = { showToast: vi.fn() };

  beforeEach(async () => {
    vi.clearAllMocks();
    authSvc.currentUser.mockReturnValue({ username: 'bm', id: 1 });
    playlistSvc.getMyPlaylists.mockReturnValue(of({ success: true, data: [makePl(1), makePl(2)] }));
    playlistSvc.getContaining.mockReturnValue(of({ success: true, data: [1] }));

    await TestBed.configureTestingModule({
      imports: [AddToPlaylistModalComponent],
      providers: [
        { provide: PlaylistService, useValue: playlistSvc },
        { provide: AuthService,     useValue: authSvc },
        { provide: ToastService,    useValue: toastSvc },
      ],
    }).compileComponents();

    fixture   = TestBed.createComponent(AddToPlaylistModalComponent);
    component = fixture.componentInstance;
    component.trackId = 99;
  });

  it('loads playlists and pendingIds on init', () => {
    fixture.detectChanges();
    expect(playlistSvc.getMyPlaylists).toHaveBeenCalled();
    expect(playlistSvc.getContaining).toHaveBeenCalledWith(99, 'bm');
    expect(component.playlists().length).toBe(2);
    expect(component.pendingIds().has(1)).toBe(true);
    expect(component.pendingIds().has(2)).toBe(false);
    expect(component.loading()).toBe(false);
  });

  it('adds to pendingIds when unchecked playlist is toggled', () => {
    fixture.detectChanges();
    component.togglePending(makePl(2));
    expect(component.pendingIds().has(2)).toBe(true);
    // API calls happen only on saveChanges(), not on toggle
    expect(playlistSvc.addTrack).not.toHaveBeenCalled();
  });

  it('removes from pendingIds when checked playlist is toggled', () => {
    fixture.detectChanges();
    component.togglePending(makePl(1));
    expect(component.pendingIds().has(1)).toBe(false);
    expect(playlistSvc.removeTrack).not.toHaveBeenCalled();
  });

  it('detects pending changes correctly', () => {
    fixture.detectChanges();
    expect(component.hasPendingChanges()).toBe(false);
    component.togglePending(makePl(2));
    expect(component.hasPendingChanges()).toBe(true);
    component.togglePending(makePl(2)); // revert
    expect(component.hasPendingChanges()).toBe(false);
  });

  it('calls addTrack and removeTrack on saveChanges()', async () => {
    playlistSvc.addTrack.mockReturnValue(of({ success: true, data: undefined }));
    playlistSvc.removeTrack.mockReturnValue(of({ success: true, data: undefined }));
    fixture.detectChanges();

    component.togglePending(makePl(2)); // add pl 2
    component.togglePending(makePl(1)); // remove pl 1

    await component.saveChanges();

    expect(playlistSvc.addTrack).toHaveBeenCalledWith(2, 99);
    expect(playlistSvc.removeTrack).toHaveBeenCalledWith(1, 99);
  });

  it('creates playlist and adds to pendingIds on createAndAdd()', () => {
    const newPl = makePl(3, 'New PL');
    playlistSvc.createPlaylist.mockReturnValue(of({ success: true, data: newPl }));
    fixture.detectChanges();

    component.newTitle = 'New PL';
    component.showCreate.set(true);
    component.createAndAdd();

    expect(playlistSvc.createPlaylist).toHaveBeenCalled();
    expect(component.playlists().some(p => p.id === 3)).toBe(true);
    expect(component.pendingIds().has(3)).toBe(true);
    expect(component.showCreate()).toBe(false);
    expect(component.newTitle).toBe('');
  });

  it('emits closed event when close() is called', () => {
    fixture.detectChanges();
    let emitted = false;
    component.closed.subscribe(() => (emitted = true));
    component.close();
    expect(emitted).toBe(true);
  });
});
