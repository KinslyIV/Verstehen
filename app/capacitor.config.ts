import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
	appId: 'local.verstehen.app',
	appName: 'Verstehen',
	webDir: 'build-android',
	server: { androidScheme: 'http' },
	plugins: { CapacitorHttp: { enabled: false } }
};

export default config;
