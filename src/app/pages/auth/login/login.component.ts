import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';

@Component({
  selector: 'app-login',
  standalone : true,
  imports: [ CommonModule, RouterModule, FormsModule ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {

  
  identifier : string = '';
  password : string = '';
  remember : boolean = false;

  loading = signal(false);
  error   = signal<string | null>(null);

  constructor(private authService : AuthService, private router : Router ) {}

  onSubmit() {
    this.loading.set(true);
    this.error.set(null);

    this.authService.login(this.identifier, this.password, this.remember)
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success) {
            this.router.navigate(['/']);
          } else {
            this.error.set(res.feedback?.message ?? 'Identifiants incorrects.');
          }
        },
        error: (err) => {
          this.error.set(
            err?.error?.feedback?.message ?? 'Une erreur est survenue. Réessayez.'
          );
        },
      });
  }


}
