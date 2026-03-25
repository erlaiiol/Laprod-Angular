import { CommonModule } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';
import { Router, RouterModule, RouterOutlet } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { FormBuilder, FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';

@Component({
  selector: 'app-login',
  standalone : true,
  imports: [ CommonModule, RouterModule, FormsModule ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {

  
  identifier = '';
  password = '';
  remember = false;

  loading = signal(false);

  constructor(private authService : AuthService, private router : Router ) {


      
      {
  }
  };

  onSubmit() {

    this.loading.set(true);  

          this.authService.login(
            this.identifier, 
            this.password, 
            this.remember)
            .pipe(
              finalize(() => this.loading.set(false)))
          .subscribe({
            next: (res) => {
              if (res.success) {
                console.log('Connexion réussie');
                this.router.navigate(['/'])

              } else {
                console.log('erreur login');
              }
            },
            error : (err) => {
              console.error(err);
            }
          });
  }


}
