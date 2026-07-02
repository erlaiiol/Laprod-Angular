/**
 * Mocks de services Angular — exports centralisés.
 *
 * Usage dans un spec de composant :
 *   import { createMockAuthService, createMockTrackService } from '../../../testing/mocks';
 *
 *   const authSvc = createMockAuthService(USER_ADMIN);
 *   const trackSvc = createMockTrackService(TRACK_HIGH_PRICE);
 */

export * from './service-mocks';
export * from './http-testing';
