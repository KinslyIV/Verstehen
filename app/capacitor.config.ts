import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
	appId: 'local.verstehen.app',
	appName: 'Verstehen',
	webDir: 'build',
	server: { androidScheme: 'http' }
};

export default config;
