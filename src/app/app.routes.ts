import { Routes } from '@angular/router';

// Pages (smart — fetch des données)
import { HomeComponent }   from './pages/home/home.component';
import { UploadComponent } from './components/upload/upload.component';
import { LoginComponent } from './pages/auth/login/login.component';

export const routes: Routes = [
  { path: '',       component: HomeComponent },
  { path: 'upload', component: UploadComponent },
  { path: 'login', component: LoginComponent }
  // { path: 'track/:id', component: TrackDetailComponent },  ← prochaine page
];