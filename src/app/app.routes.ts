import { Routes } from '@angular/router';
import { authGuard }         from './guards/auth.guard';
import { adminGuard }        from './guards/admin.guard';
import { testimonialsGuard } from './guards/testimonials.guard';

// data.preload = true → chunk préchargé en idle après le premier rendu
// (voir routing/idle-preload.strategy.ts). Réservé aux routes du parcours
// principal ; ne pas le poser partout.
export const routes: Routes = [
  { path: '',
    loadComponent: () => import('./pages/home/home.component').then(m => m.HomeComponent),
    data: { preload: true } },

  { path: 'upload-track',
    loadComponent: () => import('./pages/upload-track/upload-track.component').then(m => m.UploadTrackComponent),
    canActivate: [authGuard] },

  { path: 'login',
    loadComponent: () => import('./pages/auth/login/login.component').then(m => m.LoginComponent) },

  { path: 'register',
    loadComponent: () => import('./pages/auth/register/register.component').then(m => m.RegisterComponent) },

  { path: 'verify-email',
    loadComponent: () => import('./pages/auth/verify-email/verify-email.component').then(m => m.VerifyEmailComponent) },

  { path: 'oauth-callback',
    loadComponent: () => import('./pages/auth/oauth-callback/oauth-callback.component').then(m => m.OauthCallbackComponent) },

  { path: 'complete-profile',
    loadComponent: () => import('./pages/auth/complete-profile/complete-profile.component').then(m => m.CompleteProfileComponent) },

  { path: 'select-role',
    loadComponent: () => import('./pages/auth/select-role/select-role.component').then(m => m.SelectRoleComponent) },

  { path: 'track/:id',
    loadComponent: () => import('./pages/track-detail/track-detail.component').then(m => m.TrackDetailComponent),
    data: { preload: true } },

  { path: 'playlist/:id',
    loadComponent: () => import('./pages/playlist/playlist.component').then(m => m.PlaylistComponent) },

  { path: 'edit-track/:id',
    loadComponent: () => import('./pages/edit-track/edit-track.component').then(m => m.EditTrackComponent),
    canActivate: [authGuard] },

  { path: 'contract/:trackId/:format',
    loadComponent: () => import('./pages/track-contract-config/track-contract-config.component').then(m => m.TrackContractConfigComponent) },

  { path: 'wallet',
    loadComponent: () => import('./pages/wallet/wallet.component').then(m => m.WalletComponent),
    canActivate: [authGuard] },

  { path: 'submit-sample',
    loadComponent: () => import('./pages/auth/submit-mixmaster-sample/submit-mixmaster-sample.component').then(m => m.SubmitMixmasterSampleComponent),
    canActivate: [authGuard] },

  { path: 'profile/edit',
    loadComponent: () => import('./pages/profile/edit-profile/edit-profile.component').then(m => m.EditProfileComponent),
    canActivate: [authGuard] },

  { path: 'profile/security',
    loadComponent: () => import('./pages/profile/edit-security/edit-security.component').then(m => m.EditSecurityComponent),
    canActivate: [authGuard] },

  { path: 'profile/:username',
    loadComponent: () => import('./pages/profile/profile.component').then(m => m.ProfileComponent) },

  { path: 'notifications',
    loadComponent: () => import('./pages/notifications/notifications.component').then(m => m.NotificationsComponent),
    canActivate: [authGuard] },

  { path: 'contact',
    loadComponent: () => import('./pages/contact/contact.component').then(m => m.ContactComponent) },

  { path: 'temoignages',
    loadComponent: () => import('./pages/testimonials/testimonials.component').then(m => m.TestimonialsComponent),
    canActivate: [testimonialsGuard] },

  { path: 'dashboard/beatmaker',
    loadComponent: () => import('./pages/dashboard/dashboard-beatmaker/dashboard-beatmaker.component').then(m => m.DashboardBeatmakerComponent),
    canActivate: [authGuard] },

  { path: 'dashboard/artist',
    loadComponent: () => import('./pages/dashboard/dashboard-artist/dashboard-artist.component').then(m => m.DashboardArtistComponent),
    canActivate: [authGuard] },

  { path: 'dashboard/mix-engineer',
    loadComponent: () => import('./pages/dashboard/dashboard-mix-engineer/dashboard-mix-engineer.component').then(m => m.DashboardMixEngineerComponent),
    canActivate: [authGuard] },

  { path: 'purchases',
    loadComponent: () => import('./pages/purchases/purchases.component').then(m => m.PurchasesComponent),
    canActivate: [authGuard] },

  // authGuard et non premiumGuard : la création est réservée au Premium (contrôlée
  // côté serveur), mais un Premium expiré doit pouvoir accéder à la page pour
  // désactiver des codes encore actifs sur son catalogue.
  { path: 'promo-codes',
    loadComponent: () => import('./pages/promo-codes/promo-codes.component').then(m => m.PromoCodesComponent),
    canActivate: [authGuard] },

  // Idem : la création est Premium (contrôlée serveur), mais un Premium expiré
  // doit pouvoir consulter ses résultats passés et annuler une campagne planifiée.
  { path: 'campagnes',
    loadComponent: () => import('./pages/campaigns/campaigns.component').then(m => m.CampaignsComponent),
    canActivate: [authGuard] },

  // Publique et sans guard : se désinscrire doit être au moins aussi simple que
  // de s'inscrire (art. L.34-5 CPCE). Exiger un login serait une friction illégale.
  { path: 'desinscription',
    loadComponent: () => import('./pages/unsubscribe/unsubscribe.component').then(m => m.UnsubscribeComponent) },

  { path: 'mix/engineers',
    loadComponent: () => import('./pages/mixmaster/engineers/engineers.component').then(m => m.MixmasterEngineersComponent) },

  { path: 'mix/order/:engineerId',
    loadComponent: () => import('./pages/mixmaster/order/order.component').then(m => m.MixmasterOrderComponent) },

  { path: 'mix/payment-success',
    loadComponent: () => import('./pages/mixmaster/payment-success/payment-success.component').then(m => m.MixPaymentSuccessComponent),
    canActivate: [authGuard] },

  { path: 'payment/track/success',
    loadComponent: () => import('./pages/payment-success/payment-success.component').then(m => m.TrackPaymentSuccessComponent),
    canActivate: [authGuard] },

  { path: 'contract-builder',
    loadComponent: () => import('./pages/contract-builder/contract-builder.component').then(m => m.ContractBuilderComponent) },

  // Aperçu public (invités et non-Pro) : contrat d'exemple, lecture seule.
  { path: 'contract-builder/demo',
    loadComponent: () => import('./pages/contract-builder/builder-form/builder-form.component').then(m => m.BuilderFormComponent),
    data: { demo: true } },

  { path: 'contract-builder/:id',
    loadComponent: () => import('./pages/contract-builder/builder-form/builder-form.component').then(m => m.BuilderFormComponent),
    canActivate: [authGuard] },

  { path: 'contract-analyzer',
    loadComponent: () => import('./pages/contract-analyzer/contract-analyzer.component').then(m => m.ContractAnalyzerComponent) },

  { path: 'premium',
    loadComponent: () => import('./pages/premium/premium.component').then(m => m.PremiumComponent),
    canActivate: [authGuard] },

  { path: 'submit-master-sample',
    loadComponent: () => import('./pages/auth/submit-master-sample/submit-master-sample.component').then(m => m.SubmitMasterSampleComponent),
    canActivate: [authGuard] },

  { path: 'cgu',
    loadComponent: () => import('./pages/legal/cgu/cgu.component').then(m => m.CguComponent) },

  { path: 'privacy',
    loadComponent: () => import('./pages/legal/privacy/privacy.component').then(m => m.PrivacyComponent) },

  { path: 'mentions-legales',
    loadComponent: () => import('./pages/legal/mentions-legales/mentions-legales.component').then(m => m.MentionsLegalesComponent) },

  { path: 'dmca',
    loadComponent: () => import('./pages/legal/dmca/dmca.component').then(m => m.DmcaComponent) },

  { path: 'cookies',
    loadComponent: () => import('./pages/legal/cookies/cookies.component').then(m => m.CookiesComponent) },

  { path: 'admin',
    loadComponent: () => import('./pages/admin/admin.component').then(m => m.AdminComponent),
    canActivate: [adminGuard] },

  { path: 'erreur',
    loadComponent: () => import('./pages/not-found/not-found.component').then(m => m.NotFoundComponent) },

  { path: '**',
    loadComponent: () => import('./pages/not-found/not-found.component').then(m => m.NotFoundComponent) },
];
