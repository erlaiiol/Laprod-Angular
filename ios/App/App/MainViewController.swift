import Capacitor

// Enregistre à la main les plugins Capacitor LOCAUX de l'app.
//
// L'enregistrement automatique de Capacitor (CapacitorBridge.registerPlugins)
// ne lit que `packageClassList` dans capacitor.config.json, et `cap sync` ne
// remplit cette liste qu'avec les plugins installés par npm. Une classe écrite
// directement dans ios/App/App/ n'y figure jamais : sans cet enregistrement
// explicite, son load() n'est jamais appelé et tout appel JS échoue avec
// « plugin is not implemented on ios », même si le projet compile sans erreur.
//
// Main.storyboard pointe sur cette classe (customClass="MainViewController",
// customModule="App") à la place du CAPBridgeViewController de Capacitor.
// @objc(MainViewController) fige le nom Objective-C pour que la résolution
// d'Interface Builder ne dépende pas du nom de module Swift.
@objc(MainViewController)
class MainViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(PitchMonitorPlugin())
        bridge?.registerPluginInstance(StoreKitPurchasePlugin())
    }
}
