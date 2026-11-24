import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
	appId: 'local.verstehen.app',
	appName: 'Verstehen',
	backgroundColor: '#0a0a0a',
	webDir: 'build-android',
	server: { androidScheme: 'http' },
	plugins: { CapacitorHttp: { enabled: false } }
};

export default config;
