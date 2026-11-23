package local.verstehen.app;

/** Decides which http hosts the WebView may reach: the page itself and Tailscale addresses. */
final class CleartextGuard {
    private static final String EMULATOR_HOST = "10.0.2.2";

    private CleartextGuard() {}

    static boolean allows(String scheme, String host, boolean debug) {
        if (!"http".equalsIgnoreCase(scheme)) return true;
        if (host == null) return false;
        return host.equals("localhost") || isTailscaleAddress(host) || (debug && host.equals(EMULATOR_HOST));
    }

    /** True for dotted-decimal 100.64.0.0/10; any other spelling of an address is refused. */
    static boolean isTailscaleAddress(String host) {
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) return false;
        int[] octets = new int[4];
        for (int i = 0; i < 4; i++) {
            if (!parts[i].matches("0|[1-9][0-9]{0,2}")) return false;
            octets[i] = Integer.parseInt(parts[i]);
            if (octets[i] > 255) return false;
        }
        return octets[0] == 100 && octets[1] >= 64 && octets[1] <= 127;
    }
}
