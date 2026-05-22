import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { vi } from 'vitest';
import { PlaylistButtonComponent } from './playlist-button.component';
import { Track } from '../../services/track.service';

const mockTrack = (playlist_count: number, first_playlist_image: string | null = null): Track =>
  ({
    id: 1,
    title: 'Test Beat',
    composer_user: { username: 'beatmaker1' },
    stream_url: '/stream/1',
    image_file: 'images/tracks/test.jpg',
    bpm: 120,
    key: 'C major',
    style: 'Trap',
    price_mp3: 9.99,
    tags: [],
    is_approved: true,
    full_stream_url: null,
    playlist_count,
    first_playlist_image,
  }) as Track;

describe('PlaylistButtonComponent', () => {
  let fixture: ComponentFixture<PlaylistButtonComponent>;
  let component: PlaylistButtonComponent;
  const mockRouter = { navigate: vi.fn() };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PlaylistButtonComponent],
      providers: [{ provide: Router, useValue: mockRouter }],
    }).compileComponents();

    fixture = TestBed.createComponent(PlaylistButtonComponent);
    component = fixture.componentInstance;
    mockRouter.navigate.mockReset();
  });

  it('should be created', () => {
    component.track = mockTrack(0);
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('renders nothing when playlist_count is 0', () => {
    component.track = mockTrack(0);
    fixture.detectChanges();
    const btn = fixture.nativeElement.querySelector('.playlist-btn');
    expect(btn).toBeNull();
  });

  it('renders one image when playlist_count is 1', () => {
    component.track = mockTrack(1);
    fixture.detectChanges();
    const btn = fixture.nativeElement.querySelector('.playlist-btn');
    expect(btn).not.toBeNull();
    const ghosts = fixture.nativeElement.querySelectorAll('.pl-ghost');
    expect(ghosts.length).toBe(0);
    const badge = fixture.nativeElement.querySelector('.pl-count');
    expect(badge).toBeNull();
  });

  it('renders one ghost square when playlist_count is 2', () => {
    component.track = mockTrack(2);
    fixture.detectChanges();
    const ghosts = fixture.nativeElement.querySelectorAll('.pl-ghost');
    expect(ghosts.length).toBe(1);
    const badge = fixture.nativeElement.querySelector('.pl-count');
    expect(badge).toBeNull();
  });

  it('renders two ghost squares and +N badge when playlist_count >= 3', () => {
    component.track = mockTrack(5);
    fixture.detectChanges();
    const ghosts = fixture.nativeElement.querySelectorAll('.pl-ghost');
    expect(ghosts.length).toBe(2);
    const badge = fixture.nativeElement.querySelector('.pl-count');
    expect(badge).not.toBeNull();
    expect(badge.textContent).toContain('5');
  });

  it('navigates to profile with highlight_track query param on click', () => {
    component.track = mockTrack(2);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('.playlist-btn');
    btn.click();
    expect(mockRouter.navigate).toHaveBeenCalledWith(
      ['/profile', 'beatmaker1'],
      { queryParams: { highlight_track: 1 } },
    );
  });
});
