import Capacitor
import AuthenticationServices

// ── Connexion OAuth via le navigateur système (ASWebAuthenticationSession) ────
//
// Google refuse l'authentification dans une WebView embarquée, et un simple
// lien depuis la WebView ouvrait Safari : la connexion se terminait alors sur
// le site web, jamais dans l'app. ASWebAuthenticationSession est l'API prévue
// par Apple pour ce cas : feuille système partageant les cookies Safari, qui
// intercepte la redirection finale vers net.laprod.app://… et rend l'URL au JS
// (sans la boîte « Ouvrir dans LaProd ? » qu'afficherait SFSafariViewController).
//
// Le serveur choisit cette redirection quand le flow est lancé avec
// ?platform=mobile (routes/auth_api.py, _MOBILE_OAUTH_SCHEME).
// Côté TypeScript : AuthService.startGoogleLogin / startAppleWebLogin.
//
// Plugin LOCAL (pas un paquet npm) : `cap sync` ne le découvre pas, il est
// enregistré à la main dans MainViewController.swift.

@objc(WebAuthSessionPlugin)
public class WebAuthSessionPlugin: CAPPlugin, CAPBridgedPlugin, ASWebAuthenticationPresentationContextProviding {

    public let identifier    = "WebAuthSessionPlugin"
    public let jsName        = "WebAuthSession"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
    ]

    // Retenue tant que la feuille est ouverte : sinon libérée aussitôt.
    private var session: ASWebAuthenticationSession?

    @objc func start(_ call: CAPPluginCall) {
        guard let urlString = call.getString("url"), let url = URL(string: urlString),
              let scheme = call.getString("callbackScheme"), !scheme.isEmpty else {
            call.reject("url et callbackScheme requis", "INVALID_ARGUMENT")
            return
        }

        DispatchQueue.main.async {
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: scheme) { [weak self] callbackURL, error in
                self?.session = nil
                if let callbackURL = callbackURL {
                    call.resolve(["url": callbackURL.absoluteString])
                } else if let err = error as? ASWebAuthenticationSessionError, err.code == .canceledLogin {
                    call.reject("Connexion annulée", "CANCELED")
                } else {
                    call.reject(error?.localizedDescription ?? "Échec de la connexion", "FAILED")
                }
            }
            session.presentationContextProvider = self
            // Partage la session Safari : l'utilisateur déjà connecté à Google
            // dans Safari n'a pas à retaper son mot de passe.
            session.prefersEphemeralWebBrowserSession = false
            self.session = session
            if !session.start() {
                self.session = nil
                call.reject("Impossible d'ouvrir la connexion", "FAILED")
            }
        }
    }

    public func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        return bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
