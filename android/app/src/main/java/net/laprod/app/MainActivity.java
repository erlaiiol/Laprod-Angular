package net.laprod.app;

import android.os.Bundle;
import androidx.activity.EdgeToEdge;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(PitchMonitorPlugin.class);
        super.onCreate(savedInstanceState);
        // targetSdk 36 (Android 15+) impose l'edge-to-edge : @capacitor-community/safe-area
        // gère le padding/insets correspondant côté WebView (voir native-shell.service.ts).
        EdgeToEdge.enable(this);
    }
}
