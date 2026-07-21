import type { User } from '../../app/services/auth.service';

// ── Objets de référence utilisateurs ─────────────────────────────────────────
// Correspondent à la forme produite par serializers.user_auth() côté Flask.

/** Beatmaker sur plan gratuit — cas le plus courant dans les tests. */
export const USER_FREE_BEATMAKER: User = {
  id: 1,
  username: 'free_beatmaker',
  email: 'free@test.laprod.fr',
  profile_image: 'images/default_profile.png',
  roles: {
    is_admin:                       false,
    is_beatmaker:                   true,
    is_mix_engineer:                false,
    is_artist:                      false,
    is_producer:                    false,
    is_mixmaster_engineer:          false,
    is_certified_producer_arranger: false,
  },
  user_type_selected: true,
  email_verified:     true,
  notif_count:        0,
  upload_track_tokens: 2,
  topline_tokens:      5,
  is_premium:          false,
  subscription_plan:   'free',
  preferred_tag_category: null,
};

/** Beatmaker sur plan pro — accès complet, tokens élevés. */
export const USER_PRO_BEATMAKER: User = {
  ...USER_FREE_BEATMAKER,
  id:       2,
  username: 'pro_beatmaker',
  email:    'pro@test.laprod.fr',
  upload_track_tokens: 30,
  topline_tokens:      200,
  is_premium:        true,
  subscription_plan: 'pro',
};

/** Artiste pur — dépose des toplines, commande des sessions mix/master. */
export const USER_ARTIST: User = {
  ...USER_FREE_BEATMAKER,
  id:       3,
  username: 'artist_user',
  email:    'artist@test.laprod.fr',
  roles: {
    ...USER_FREE_BEATMAKER.roles,
    is_beatmaker: false,
    is_artist:    true,
  },
};

/** Administrateur plateforme. */
export const USER_ADMIN: User = {
  ...USER_FREE_BEATMAKER,
  id:       4,
  username: 'admin',
  email:    'admin@test.laprod.fr',
  roles: {
    ...USER_FREE_BEATMAKER.roles,
    is_admin:     true,
    is_beatmaker: false,
  },
};

/** Ingénieur mix/master certifié. */
export const USER_MIX_ENGINEER: User = {
  ...USER_FREE_BEATMAKER,
  id:       5,
  username: 'mix_engineer',
  email:    'engineer@test.laprod.fr',
  roles: {
    ...USER_FREE_BEATMAKER.roles,
    is_beatmaker:          false,
    is_mix_engineer:       true,
    is_mixmaster_engineer: true,
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Construit une réponse de login réussie autour d'un utilisateur. */
export function makeLoginSuccess(user: User = USER_FREE_BEATMAKER) {
  return {
    success: true as const,
    feedback: { level: 'success', message: 'Connexion réussie' },
    data: {
      tokens: { access_token: 'jwt-test-access-token', refresh_token: 'jwt-test-refresh-token' },
      user,
    },
  };
}
