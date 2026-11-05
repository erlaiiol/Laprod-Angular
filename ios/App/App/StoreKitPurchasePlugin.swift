import Capacitor
import StoreKit

// ── Achat intégré Apple (StoreKit 2) ──────────────────────────────────────────
//
// Responsabilité unique : présenter la feuille d'achat d'Apple pour un
// abonnement LaProd+ et remettre au JS la transaction SIGNÉE (JWS), telle
// quelle. Ce plugin ne décide jamais qu'un achat est valide : le serveur
// revérifie la signature contre les certificats d'Apple avant de créditer
// (utils/apple_iap.py). Le contrôle `.verified` fait ici n'est que celui de
// StoreKit sur l'appareil.
//
// Côté TypeScript : src/app/services/ios-purchase.service.ts.
// Pourquoi l'abonnement passe par Apple sur iOS : docs/architecture.md
// § Paiements sur iOS.
//
// Plugin LOCAL (pas un paquet npm) : `cap sync` ne le découvre pas, il est
// enregistré à la main dans MainViewController.swift.

@objc(StoreKitPurchasePlugin)
public class StoreKitPurchasePlugin: CAPPlugin, CAPBridgedPlugin {

    public let identifier    = "StoreKitPurchasePlugin"
    public let jsName        = "StoreKitPurchase"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getProducts",           returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "purchase",              returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "restorePurchases",      returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getActiveEntitlements", returnType: CAPPluginReturnPromise),
    ]

    private var transactionListenerTask: Task<Void, Never>?

    // Une transaction peut arriver en dehors de tout appel à purchase() :
    // validation parentale (« Demander l'autorisation d'achat »), achat
    // interrompu puis repris. Apple demande d'écouter Transaction.updates
    // pendant toute la vie de l'app ; chaque transaction est relayée au JS,
    // qui la fait vérifier par le serveur comme un achat normal.
    override public func load() {
        transactionListenerTask = Task.detached { [weak self] in
            for await update in Transaction.updates {
                guard let self else { return }
                if case .verified(let transaction) = update {
                    await transaction.finish()
                }
                self.notifyListeners("transactionsUpdated", data: [
                    "transactionJWS": update.jwsRepresentation,
                ])
            }
        }
    }

    deinit {
        transactionListenerTask?.cancel()
    }

    // ── getProducts ───────────────────────────────────────────────────────────
    //
    // Le prix affiché dans l'app iOS DOIT être celui de l'App Store (devise et
    // montant du compte Apple de l'utilisateur), pas celui de la grille Stripe.

    @objc func getProducts(_ call: CAPPluginCall) {
        let ids = (call.getArray("productIds") ?? []).compactMap { $0 as? String }
        Task {
            do {
                let products = try await Product.products(for: ids)
                call.resolve(["products": products.map { product in
                    [
                        "productId":    product.id,
                        "displayName":  product.displayName,
                        "description":  product.description,
                        "displayPrice": product.displayPrice,
                    ]
                }])
            } catch {
                call.reject("PRODUCTS_FAILED", error.localizedDescription, error)
            }
        }
    }

    // ── purchase ──────────────────────────────────────────────────────────────

    @objc func purchase(_ call: CAPPluginCall) {
        guard let productId = call.getString("productId") else {
            call.reject("productId is required")
            return
        }
        // Jeton de compte fourni par le serveur : Apple le resigne dans la
        // transaction, ce qui empêche de créditer l'achat sur un autre compte.
        var options: Set<Product.PurchaseOption> = []
        if let token = call.getString("appAccountToken"), let uuid = UUID(uuidString: token) {
            options.insert(.appAccountToken(uuid))
        }

        Task {
            do {
                let products = try await Product.products(for: [productId])
                guard let product = products.first else {
                    call.reject("PRODUCT_NOT_FOUND", "No App Store product found for id \(productId)")
                    return
                }
                let result = try await product.purchase(options: options)
                switch result {
                case .success(let verification):
                    if case .verified(let transaction) = verification {
                        await transaction.finish()
                    }
                    call.resolve(["transactionJWS": verification.jwsRepresentation])
                case .userCancelled:
                    call.reject("USER_CANCELLED", "Purchase sheet dismissed.")
                case .pending:
                    // Validation externe en attente : la transaction arrivera
                    // plus tard par Transaction.updates (voir load()).
                    call.reject("PENDING", "Purchase is pending approval.")
                @unknown default:
                    call.reject("UNKNOWN", "Unknown StoreKit purchase result.")
                }
            } catch {
                call.reject("PURCHASE_FAILED", error.localizedDescription, error)
            }
        }
    }

    // ── restorePurchases ──────────────────────────────────────────────────────
    //
    // AppStore.sync() resynchronise l'historique de l'appareil avec Apple (peut
    // demander le mot de passe du compte Apple) : réservé au bouton explicite
    // « Restaurer mes achats ».

    @objc func restorePurchases(_ call: CAPPluginCall) {
        Task {
            do {
                try await AppStore.sync()
                let jwsList = await currentEntitlementJWSList()
                call.resolve(["transactions": jwsList.map { ["transactionJWS": $0] }])
            } catch {
                call.reject("RESTORE_FAILED", error.localizedDescription, error)
            }
        }
    }

    // ── getActiveEntitlements ─────────────────────────────────────────────────
    //
    // Même chose sans appel réseau ni demande de mot de passe : rattrapage
    // silencieux d'un achat dont la vérification serveur aurait échoué.

    @objc func getActiveEntitlements(_ call: CAPPluginCall) {
        Task {
            let jwsList = await currentEntitlementJWSList()
            call.resolve(["transactions": jwsList.map { ["transactionJWS": $0] }])
        }
    }

    private func currentEntitlementJWSList() async -> [String] {
        var jwsList: [String] = []
        for await entitlement in Transaction.currentEntitlements {
            jwsList.append(entitlement.jwsRepresentation)
        }
        return jwsList
    }
}
