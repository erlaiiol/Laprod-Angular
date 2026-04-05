import { Component, computed, inject, OnInit } from '@angular/core';
import { RouterLink, Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { ErrorService, AppError, ErrorCode } from '../../services/error.service';

interface ErrorConfig {
  code:     ErrorCode;
  icon:     string;
  title:    string;
  message:  string;
  showBack: boolean;
  showHome: boolean;
  showLogin: boolean;
  accent:   'violet' | 'red' | 'orange' | 'blue';
}

const CONFIGS: Record<ErrorCode, Omit<ErrorConfig, 'code'>> = {
  404: {
    icon:     'bi-map',
    title:    'Page introuvable',
    message:  'Cette page n\'existe pas ou a été déplacée. Vérifiez l\'URL ou retournez à l\'accueil.',
    showBack: true,
    showHome: true,
    showLogin: false,
    accent:   'violet',
  },
  403: {
    icon:     'bi-shield-lock',
    title:    'Accès interdit',
    message:  'Vous n\'avez pas les permissions nécessaires pour accéder à cette page.',
    showBack: true,
    showHome: true,
    showLogin: false,
    accent:   'orange',
  },
  500: {
    icon:     'bi-exclamation-octagon',
    title:    'Erreur serveur',
    message:  'Une erreur interne s\'est produite. Nos équipes ont été notifiées. Veuillez réessayer dans quelques instants.',
    showBack: false,
    showHome: true,
    showLogin: false,
    accent:   'red',
  },
  503: {
    icon:     'bi-cloud-slash',
    title:    'Serveur indisponible',
    message:  'Le serveur est temporairement indisponible ou en maintenance. Veuillez réessayer dans quelques instants.',
    showBack: false,
    showHome: false,
    showLogin: false,
    accent:   'orange',
  },
  0: {
    icon:     'bi-wifi-off',
    title:    'Connexion impossible',
    message:  'Impossible de joindre le serveur. Vérifiez votre connexion internet et réessayez.',
    showBack: false,
    showHome: false,
    showLogin: false,
    accent:   'blue',
  },
};

@Component({
  selector: 'app-not-found',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './not-found.component.html',
  styleUrl: './not-found.component.scss',
})
export class NotFoundComponent implements OnInit {

  private errorSvc = inject(ErrorService);
  private router   = inject(Router);
  readonly auth    = inject(AuthService);

  /** Résolution de l'erreur courante : service > fallback 404 */
  readonly error = computed<AppError>(() => this.errorSvc.current() ?? { code: 404 });

  readonly config = computed<ErrorConfig>(() => {
    const err = this.error();
    return { code: err.code, ...CONFIGS[err.code] };
  });

  ngOnInit(): void {
    // Nettoie l'état d'erreur une fois consommé (pour les navigations suivantes)
    // On garde l'état pour le rendu mais on le réinitialise au prochain cycle.
    // NOTE: on ne clear pas immédiatement pour que computed() ait le temps de lire.
  }

  retry(): void {
    window.location.reload();
  }

  goBack(): void {
    history.back();
  }
}
