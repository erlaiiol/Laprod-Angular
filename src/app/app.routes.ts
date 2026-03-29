import { Routes } from '@angular/router';

// Pages (smart — fetch des données)
import { HomeComponent }           from './pages/home/home.component';
import { UploadComponent }         from './components/upload/upload.component';
import { LoginComponent }          from './pages/auth/login/login.component';
import { TrackDetailComponent }    from './pages/track-detail/track-detail.component';
import { ContractConfigComponent } from './pages/contract-config/contract-config.component';
import { WalletComponent }         from './pages/wallet/wallet.component';
import { RegisterComponent }        from './pages/auth/register/register.component';
import { OauthCallbackComponent }   from './pages/auth/oauth-callback/oauth-callback.component';
import { CompleteProfileComponent } from './pages/auth/complete-profile/complete-profile.component';
import { SelectRoleComponent }           from './pages/auth/select-role/select-role.component';
import { SubmitMixmasterSampleComponent } from './pages/auth/submit-mixmaster-sample/submit-mixmaster-sample.component';

export const routes: Routes = [
  { path: '',                              component: HomeComponent },
  { path: 'upload',                        component: UploadComponent },
  { path: 'login',                         component: LoginComponent },
  { path: 'register',                      component: RegisterComponent },
  { path: 'oauth-callback',               component: OauthCallbackComponent },
  { path: 'complete-profile',             component: CompleteProfileComponent },
  { path: 'select-role',                  component: SelectRoleComponent },
  { path: 'track/:id',                     component: TrackDetailComponent },
  { path: 'contract/:trackId/:format',     component: ContractConfigComponent },
  { path: 'wallet',                        component: WalletComponent },
  { path: 'submit-sample',                 component: SubmitMixmasterSampleComponent },
];
