import { vi } from 'vitest';
import { of } from 'rxjs';

import type { User } from '../../app/services/auth.service';
import { USER_FREE_BEATMAKER, makeLoginSuccess } from '../data/users';
import { TRACK_STANDARD } from '../data/tracks';
import { WALLET_WITH_BALANCE } from '../data/wallet';

// ── AuthService ───────────────────────────────────────────────────────────────

/**
 * Crée un mock AuthService avec des retours par défaut cohérents.
 *
 * Surcharger un retour dans un test :
 *   const authSvc = createMockAuthService(USER_ADMIN);
 *   authSvc.isAdmin.mockReturnValue(true);
 */
export function createMockAuthService(user: User | null = USER_FREE_BEATMAKER) {
  return {
    currentUser:      vi.fn().mockReturnValue(user),
    isLoggedIn:       vi.fn().mockReturnValue(user !== null),
    isAdmin:          vi.fn().mockReturnValue(user?.roles?.is_admin ?? false),
    isBeatmaker:      vi.fn().mockReturnValue(user?.roles?.is_beatmaker ?? false),
    isMixEngineer:    vi.fn().mockReturnValue(user?.roles?.is_mix_engineer ?? false),
    getToken:         vi.fn().mockReturnValue(user !== null ? 'fake-jwt-token' : null),
    login:            vi.fn().mockReturnValue(of(makeLoginSuccess(user ?? USER_FREE_BEATMAKER))),
    logout:           vi.fn().mockReturnValue(of({ success: true })),
    refreshToken:     vi.fn().mockReturnValue(of({ success: true })),
    me:               vi.fn().mockReturnValue(of({ success: true, data: { user } })),
  };
}

// ── TrackService ──────────────────────────────────────────────────────────────

export function createMockTrackService(track = TRACK_STANDARD) {
  return {
    getTracks: vi.fn().mockReturnValue(of({
      success: true,
      data: {
        tracks: [track],
        pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
      },
    })),
    getTrack:       vi.fn().mockReturnValue(of({ success: true, data: { track } })),
    getTrackDetail: vi.fn().mockReturnValue(of({ success: true, data: { track } })),
    getRandomTrack: vi.fn().mockReturnValue(of({ success: true, data: { track } })),
    getStaticFileUrl: vi.fn().mockImplementation((path: string) => `https://cdn.laprod.fr/${path}`),
  };
}

// ── PaymentService ────────────────────────────────────────────────────────────

export function createMockPaymentService() {
  return {
    createCheckout: vi.fn().mockReturnValue(of({
      success: true,
      data: { checkout_url: 'https://checkout.stripe.com/test', total: 9.99 },
    })),
    verifyPayment: vi.fn().mockReturnValue(of({
      success: true,
      data: { purchase_id: 42 },
    })),
    redirectToCheckout: vi.fn(),
  };
}

// ── MixmasterService ──────────────────────────────────────────────────────────

export function createMockMixmasterService() {
  return {
    getEngineers:  vi.fn().mockReturnValue(of({ success: true, data: { engineers: [] } })),
    getEngineer:   vi.fn().mockReturnValue(of({ success: true, data: { engineer: null } })),
    getMyOrders:   vi.fn().mockReturnValue(of({ success: true, data: { orders: [] } })),
    getOrder:      vi.fn().mockReturnValue(of({ success: true, data: { order: null } })),
    createOrder:   vi.fn().mockReturnValue(of({ success: true, data: { checkout_url: 'https://checkout.stripe.com/mm_test' } })),
    verifyPayment: vi.fn().mockReturnValue(of({ success: true, data: { order_id: 301 } })),
  };
}

// ── WalletService ─────────────────────────────────────────────────────────────

export function createMockWalletService() {
  return {
    getWallet:  vi.fn().mockReturnValue(of({ success: true, data: WALLET_WITH_BALANCE })),
    getSales:   vi.fn().mockReturnValue(of({ success: true, data: { sales: [], total_revenue: 0 } })),
    withdraw:   vi.fn().mockReturnValue(of({ success: true, data: { transfer_id: 'tr_test', amount: 50 } })),
  };
}

// ── PlaylistService ───────────────────────────────────────────────────────────

export function createMockPlaylistService(playlists: any[] = []) {
  return {
    getMyPlaylists: vi.fn().mockReturnValue(of({ success: true, data: playlists })),
    getContaining:  vi.fn().mockReturnValue(of({ success: true, data: [] })),
    addTrack:       vi.fn().mockReturnValue(of({ success: true })),
    removeTrack:    vi.fn().mockReturnValue(of({ success: true })),
    createPlaylist: vi.fn().mockReturnValue(of({ success: true, data: { id: 1, title: 'New Playlist' } })),
  };
}

// ── Utilitaires simples ───────────────────────────────────────────────────────

export function createMockRouter() {
  return { navigate: vi.fn() };
}

export function createMockToastService() {
  return { showToast: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn() };
}

export function createMockUploadStatusService() {
  return {
    isUploading:   vi.fn().mockReturnValue(false),
    startUpload:   vi.fn(),
    completeUpload: vi.fn(),
    failUpload:    vi.fn(),
  };
}
