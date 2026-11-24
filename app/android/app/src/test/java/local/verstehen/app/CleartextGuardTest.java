package local.verstehen.app;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CleartextGuardTest {
    @Test
    public void allowsTheTailscaleRangeOnly() {
        for (String host : new String[] {"100.64.0.0", "100.101.102.103", "100.127.255.255"}) {
            assertTrue(host, CleartextGuard.allows("http", host, false));
        }
        for (String host : new String[] {"100.63.255.255", "100.128.0.0", "99.64.0.1", "101.64.0.1", "192.168.1.5"}) {
            assertFalse(host, CleartextGuard.allows("http", host, false));
        }
    }

    @Test
    public void refusesOtherSpellingsOfAddresses() {
        for (String host : new String[] {"100.064.0.1", "100.64.1", "100.64.0.0.1", "1684275201", "0x64.64.0.1", "100.64.0.256", "100.64.0.1.evil.com", ""}) {
            assertFalse(host, CleartextGuard.allows("http", host, false));
        }
        assertFalse(CleartextGuard.allows("http", null, false));
    }

    @Test
    public void allowsThePageItself() {
        assertTrue(CleartextGuard.allows("http", "localhost", false));
        assertFalse(CleartextGuard.allows("http", "127.0.0.1", false));
    }

    @Test
    public void allowsTheEmulatorHostOnlyInDebugBuilds() {
        assertTrue(CleartextGuard.allows("http", "10.0.2.2", true));
        assertFalse(CleartextGuard.allows("http", "10.0.2.2", false));
        assertFalse(CleartextGuard.allows("http", "10.0.2.3", true));
    }

    @Test
    public void leavesHttpsAlone() {
        assertTrue(CleartextGuard.allows("https", "example.com", false));
    }
}
