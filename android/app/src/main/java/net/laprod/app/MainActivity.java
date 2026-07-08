package net.laprod.app;

import android.os.Bundle;
import android.webkit.WebSettings;
import androidx.activity.EdgeToEdge;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(PitchMonitorPlugin.class);
        super.onCreate(savedInstanceState);

        if (BuildConfig.DEBUG) {
            // Le WebView charge l'app en HTTPS (server.androidScheme dans capacitor.config.ts),
            // donc les XHR vers le backend Flask local en HTTP (10.0.2.2:5000, cf.
            // environment.mobile-dev-android.ts) sont bloquées par la politique Mixed Content de
            // Chromium — indépendamment du cleartext réseau (network_security_config.xml).
            // Jamais activé en release (BuildConfig.DEBUG est false pour ce variant).
            this.bridge.getWebView().getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }

        // targetSdk 36 (Android 15+) impose l'edge-to-edge : @capacitor-community/safe-area
        // gère le padding/insets correspondant côté WebView (voir native-shell.service.ts).
        EdgeToEdge.enable(this);
    }
}
