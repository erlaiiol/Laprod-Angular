# Sessions JWT web et Capacitor

L’access token expire après 15 minutes en production (1 heure en développement).
Le client le renouvelle 5 minutes avant son expiration, à la reprise de l’app
native, au retour du réseau ou après un 401 d’une requête API. Les appels
simultanés partagent le même renouvellement. Une requête est rejouée une seule fois.

## Stockage

- Web : `localStorage` avec « Se souvenir de moi », `sessionStorage` sinon.
- iOS/Android persistants : `@aparajita/capacitor-secure-storage`, dans le
  Keychain iOS ou des préférences chiffrées par une clé Android Keystore.
- Sessions natives sans « Se souvenir de moi » : mémoire uniquement, jusqu’à
  destruction du processus/WebView. Google/Apple utilisent une session persistante.

Le démarrage attend la lecture du coffre avant d’activer les routes et les
requêtes. Une session native existante est migrée depuis le stockage WebView,
qui n’est effacé qu’après sauvegarde réussie. Les connexions et renouvellements
attendent l’écriture native avant d’annoncer leur succès. Les écritures et
suppressions sont ordonnées pour qu’une ancienne écriture ne restaure pas une
session déconnectée.

Le coffre n’a pas de TTL applicatif ; la validité des JWT reste décidée par le
serveur. Un coffre temporairement inaccessible affiche un bouton pour réessayer
sans supprimer la session. Les préférences chiffrées Android sont exclues des
sauvegardes/transferts, car leur clé Keystore ne se transfère pas. Le Keychain
local iOS n’utilise pas la synchronisation iCloud et peut survivre à une
réinstallation ; une déconnexion supprime les identifiants de l’app.

## Rotation et erreurs

`POST /api/auth/refresh` reçoit le **refresh token** dans `Authorization` et
renvoie `data.access_token` et `data.refresh_token`. À chaque rotation, la
validité est prolongée de la durée initiale : 1 jour pour une session courte,
30 jours pour une session mémorisée ou OAuth. Une période d’inactivité supérieure
à cette durée nécessite une connexion.

La rotation Redis est atomique. L’ancien token permet de récupérer exactement
la même paire pendant au plus 60 secondes, sans prolonger cette tolérance : cela
couvre les onglets concurrents et une réponse perdue. Ensuite, il est refusé.
La révocation par utilisateur supprime également les clés de tolérance.

Un refresh refusé avec 401/422 efface la session. Les erreurs réseau, 429 et 5xx
la conservent. Un 401 après rejeu avec le nouvel access token efface la session.
Les identifiants ne sont ajoutés qu’aux requêtes vers l’API LaProd.

Déployer le serveur avec la nouvelle réponse avant de distribuer le nouveau
client pour activer la rotation. Le nouveau client accepte aussi l’ancienne
réponse contenant seulement l’access token pendant cette transition.

Validation : tests Angular des parcours d’authentification, stockage et
intercepteur ; tests Flask/Redis de rotation, concurrence, rejeu et révocation ;
build mobile et compilations natives. Sur appareils réels, vérifier aussi une
reprise après veille, le mode avion pendant un renouvellement et la migration
d’une installation existante avec session mémorisée.
