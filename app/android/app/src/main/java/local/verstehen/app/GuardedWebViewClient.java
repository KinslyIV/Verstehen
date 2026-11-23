package local.verstehen.app;

import android.net.Uri;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;
import java.io.ByteArrayInputStream;
import java.util.Collections;

/** Capacitor's client that blocks http requests outside CleartextGuard's allowed hosts. */
class GuardedWebViewClient extends BridgeWebViewClient {
    GuardedWebViewClient(Bridge bridge) {
        super(bridge);
    }

    @Override
    public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
        Uri url = request.getUrl();
        if (CleartextGuard.allows(url.getScheme(), url.getHost(), BuildConfig.DEBUG)) {
            return super.shouldInterceptRequest(view, request);
        }
        return new WebResourceResponse(
            "text/plain", "utf-8", 403, "Blocked", Collections.emptyMap(), new ByteArrayInputStream(new byte[0]));
    }
}
