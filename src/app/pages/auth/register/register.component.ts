import { Component, signal } from '@angular/core';
import { AuthService } from '../../../services/auth.service';
import { Router, RouterModule, RouterOutlet } from '@angular/router';
import { finalize } from 'rxjs';

@Component({
  selector: 'app-register.component',
  standalone : true,
  imports: [],
  templateUrl: './register.component.html',
  styleUrl: './register.component.scss',
})
export class RegisterComponent {

  username : string = '';
  password : string = '';
  password_confirm : string = '';
  email : string = '';
  signature = '';

  loading = signal(false)

  constructor ( private authService : AuthService, private router : Router ){

  }

  onSubmit(){

    this.loading.set(true);

    this.authService.register(
      this.username,
      this.password,
      this.password_confirm,
      this.email,
      this.signature)
      .pipe(
      finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success){
            console.log('compte créé', res);
            this.router.navigate(['/login'])
          }
          else {
            console.log('échec à la création du compte.');
          }
        },
        error : (err) => {
          console.error(err);
        }
      });
  }
}
