import { Routes } from '@angular/router';
import { authGuard }  from './guards/auth.guard';
import { adminGuard } from './guards/admin.guard';

// Pages (smart — fetch des données)
import { HomeComponent }           from './pages/home/home.component';
import { UploadTrackComponent }         from './pages/upload-track/upload-track.component';
import { LoginComponent }          from './pages/auth/login/login.component';
import { TrackDetailComponent }    from './pages/track-detail/track-detail.component';
import { TrackContractConfigComponent } from './pages/track-contract-config/track-contract-config.component';
import { WalletComponent }         from './pages/wallet/wallet.component';
import { RegisterComponent }        from './pages/auth/register/register.component';
import { VerifyEmailComponent }     from './pages/auth/verify-email/verify-email.component';
import { OauthCallbackComponent }   from './pages/auth/oauth-callback/oauth-callback.component';
import { CompleteProfileComponent } from './pages/auth/complete-profile/complete-profile.component';
import { SelectRoleComponent }           from './pages/auth/select-role/select-role.component';
import { SubmitMixmasterSampleComponent } from './pages/auth/submit-mixmaster-sample/submit-mixmaster-sample.component';
import { ProfileComponent }       from './pages/profile/profile.component';
import { EditProfileComponent }   from './pages/profile/edit-profile/edit-profile.component';
import { EditSecurityComponent }  from './pages/profile/edit-security/edit-security.component';
import { NotificationsComponent } from './pages/notifications/notifications.component';
import { ContactComponent }                   from './pages/contact/contact.component';
import { DashboardBeatmakerComponent }        from './pages/dashboard/dashboard-beatmaker/dashboard-beatmaker.component';
import { DashboardArtistComponent }           from './pages/dashboard/dashboard-artist/dashboard-artist.component';
import { DashboardMixEngineerComponent }      from './pages/dashboard/dashboard-mix-engineer/dashboard-mix-engineer.component';
import { PurchasesComponent }                 from './pages/purchases/purchases.component';
import { MixmasterEngineersComponent }        from './pages/mixmaster/engineers/engineers.component';
import { MixmasterOrderComponent }            from './pages/mixmaster/order/order.component';
import { MixPaymentSuccessComponent }         from './pages/mixmaster/payment-success/payment-success.component';
import { TrackPaymentSuccessComponent }       from './pages/payment-success/payment-success.component';
import { AdminComponent }                    from './pages/admin/admin.component';
import { NotFoundComponent }                 from './pages/not-found/not-found.component';
import { EditTrackComponent }         from './pages/edit-track/edit-track.component';
import { ContractBuilderComponent }   from './pages/contract-builder/contract-builder.component';
import { BuilderFormComponent }       from './pages/contract-builder/builder-form/builder-form.component';
import { ContractAnalyzerComponent }  from './pages/contract-analyzer/contract-analyzer.component';
import { PremiumComponent }           from './pages/premium/premium.component';
import { SubmitMasterSampleComponent } from './pages/auth/submit-master-sample/submit-master-sample.component';
import { PlaylistComponent }          from './pages/playlist/playlist.component';
import { CguComponent }               from './pages/legal/cgu/cgu.component';
import { PrivacyComponent }           from './pages/legal/privacy/privacy.component';
import { MentionsLegalesComponent }   from './pages/legal/mentions-legales/mentions-legales.component';
import { DmcaComponent }              from './pages/legal/dmca/dmca.component';
import { CookiesComponent }           from './pages/legal/cookies/cookies.component';

export const routes: Routes = [
  { path: '',                              component: HomeComponent },
  { path: 'upload-track',                  component: UploadTrackComponent,            canActivate: [authGuard] },
  { path: 'login',                         component: LoginComponent },
  { path: 'register',                      component: RegisterComponent },
  { path: 'verify-email',                  component: VerifyEmailComponent },
  { path: 'oauth-callback',                component: OauthCallbackComponent },
  { path: 'complete-profile',              component: CompleteProfileComponent },
  { path: 'select-role',                   component: SelectRoleComponent },
  { path: 'track/:id',                     component: TrackDetailComponent },
  { path: 'playlist/:id',                  component: PlaylistComponent },
  { path: 'edit-track/:id',                component: EditTrackComponent,               canActivate: [authGuard] },
  { path: 'contract/:trackId/:format',     component: TrackContractConfigComponent },
  { path: 'wallet',                        component: WalletComponent,                  canActivate: [authGuard] },
  { path: 'submit-sample',                 component: SubmitMixmasterSampleComponent,   canActivate: [authGuard] },
  { path: 'profile/edit',                  component: EditProfileComponent,             canActivate: [authGuard] },
  { path: 'profile/security',              component: EditSecurityComponent,            canActivate: [authGuard] },
  { path: 'profile/:username',             component: ProfileComponent },
  { path: 'notifications',                 component: NotificationsComponent,           canActivate: [authGuard] },
  { path: 'contact',                       component: ContactComponent },
  { path: 'dashboard/beatmaker',           component: DashboardBeatmakerComponent,      canActivate: [authGuard] },
  { path: 'dashboard/artist',              component: DashboardArtistComponent,         canActivate: [authGuard] },
  { path: 'dashboard/mix-engineer',        component: DashboardMixEngineerComponent,    canActivate: [authGuard] },
  { path: 'purchases',                     component: PurchasesComponent,               canActivate: [authGuard] },
  { path: 'mix/engineers',                 component: MixmasterEngineersComponent },
  { path: 'mix/order/:engineerId',         component: MixmasterOrderComponent },
  { path: 'mix/payment-success',           component: MixPaymentSuccessComponent,       canActivate: [authGuard] },
  { path: 'payment/track/success',         component: TrackPaymentSuccessComponent,     canActivate: [authGuard] },
  { path: 'contract-builder',               component: ContractBuilderComponent },
  { path: 'contract-builder/:id',           component: BuilderFormComponent,             canActivate: [authGuard] },
  { path: 'contract-analyzer',              component: ContractAnalyzerComponent },
  { path: 'premium',                        component: PremiumComponent,                 canActivate: [authGuard] },
  { path: 'submit-master-sample',           component: SubmitMasterSampleComponent,      canActivate: [authGuard] },
  { path: 'cgu',                            component: CguComponent },
  { path: 'privacy',                        component: PrivacyComponent },
  { path: 'mentions-legales',               component: MentionsLegalesComponent },
  { path: 'dmca',                           component: DmcaComponent },
  { path: 'cookies',                        component: CookiesComponent },
  { path: 'admin',                         component: AdminComponent,                   canActivate: [adminGuard] },
  { path: 'erreur',                        component: NotFoundComponent },
  { path: '**',                            component: NotFoundComponent },
];
