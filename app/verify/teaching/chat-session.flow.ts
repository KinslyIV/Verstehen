import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/chat-session.json' });

test('chat-session', async ({ page, request, seedGraph, allowTeardownAborts }) => {
	const seededTeach = await request.post('/api/sessions', {
		data: { title: 'Intro to Slope', kind: 'teach' }
	});
	const teachId = (await seededTeach.json()).id;
	await seedGraph({
		nodes: [
			{
				id: 'n_slope',
				name: 'Slope',
				statement: 'Slope is the ratio of vertical change to horizontal change.',
				session: teachId
			}
		],
		chains: []
	});

	// Create a folder so we can also verify "New chat here" in the folder context menu.
	const folderRes = await request.post('/api/graph/sources', {
		data: { action: 'create-folder', name: 'Calculus', parent_id: null }
	});
	const folderId = (await folderRes.json()).created_folder_id;

	// Start from /session/new, verify the Sidebar Chat button and folder "New chat here".
	await page.goto('/session/new');
	await expect(page.getByRole('link', { name: 'Chat', exact: true }).first()).toHaveAttribute(
		'href',
		'/session/new?mode=chat'
	);

	await page.getByRole('button', { name: 'Calculus', exact: true }).click({ button: 'right' });
	await page.getByRole('menuitem', { name: 'New chat here' }).click();
	await expect(page).toHaveURL(new RegExp(`/session/new\\?mode=chat&folder=${folderId}$`));
	await expect(page.getByTestId('kind-chat')).toHaveAttribute('aria-current', 'page');
	await expect(
		page.getByText(
			'Ask anything, explore how Verstehen works, or prepare a lesson or practice session.'
		)
	).toBeVisible();
	await expect(
		page.getByPlaceholder('Ask about Verstehen, your notes, or anything else…')
	).toBeVisible();
	await expect(page.getByTestId('node-picker-chip')).toHaveCount(0);

	// Send a message in the Chat session to run inspection tools + prepare_session.
	await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.fill('Check my graph and prepare a calculus lesson.');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/(?!new)[^/]+$/);
	const chatId = new URL(page.url()).pathname.split('/').at(-1)!;

	// Header shows the Chat badge and has no coverage ring or phase divider.
	const sessionHeader = page.getByTestId('session-header');
	await expect(sessionHeader.getByTestId('phase-chip')).toHaveAttribute('data-phase', 'chat');
	await expect(sessionHeader.getByTestId('phase-chip')).toHaveText(/Chat/);
	await expect(page.getByTestId('coverage-ring')).toHaveCount(0);

	// The 1-click PrepareSessionCard renders with kind, title, picked node chip, and opening prompt.
	const card = page.getByTestId('prepare-session-card');
	await expect(card).toBeVisible();
	await expect(card.getByTestId('prepare-session-kind')).toHaveText(/Teaching/);
	await expect(card.getByTestId('prepare-session-title')).toHaveText(
		'Calculus: Secant to Derivative'
	);
	await expect(card.getByTestId('prepare-session-node')).toHaveText('Slope');
	await expect(card.getByTestId('prepare-session-prompt')).toHaveText(
		'Help me connect secant slopes to derivatives.'
	);
	await expect(page.getByText('prepared a 1-click Teaching launch card above.')).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('chat-launch-card.png'),
		animations: 'disabled'
	});

	// Reloading preserves the Launch Card and triggers no automatic continuation or extraction.
	await page.reload();
	await expect(card).toBeVisible();
	await expect(card.getByTestId('prepare-session-title')).toHaveText(
		'Calculus: Secant to Derivative'
	);
	const savedChat = await (await request.get(`/api/sessions/${chatId}`)).json();
	expect(savedChat.kind).toBe('chat');
	expect(savedChat.coverage).toBeNull();
	expect(savedChat.turn_in_flight).toBe(false);

	// Sidebar shows the Chat session row icon, filters by Chat, and omits graph traces in Delete.
	await page.getByTestId(`sidebar-folder-${folderId}`).click();
	const chatRow = page.getByRole('link', { name: /Check my graph and prepare/ });
	await expect(chatRow.getByLabel('Chat session')).toBeVisible();
	await page.getByTestId('kind-filter-chat').click();
	await expect(chatRow).toBeVisible();
	await expect(page.getByRole('link', { name: /Intro to Slope/ })).toHaveCount(0);
	await page.getByTestId('kind-filter-all').click();
	await expect(page.getByRole('link', { name: /Intro to Slope/ })).toBeVisible();

	await chatRow.click({ button: 'right' });
	await page.getByRole('menuitem', { name: 'Delete' }).click();
	await expect(page.getByTestId('delete-session-dialog')).toContainText(
		'Check my graph and prepare'
	);
	await expect(page.getByTestId('delete-traces')).toHaveCount(0);
	await page.getByTestId('delete-cancel').click();

	// Phone viewport check (360x780): 4-way sidebar filter, /session/new 3-way toggle, and PrepareSessionCard fit cleanly.
	await page.setViewportSize({ width: 360, height: 780 });
	await expect(card).toBeVisible();
	const cardBox = (await card.boundingBox())!;
	expect(cardBox.x).toBeGreaterThanOrEqual(0);
	expect(cardBox.x + cardBox.width).toBeLessThanOrEqual(360);
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= document.documentElement.clientWidth
		)
	).toBe(true);
	await page.screenshot({
		path: test.info().outputPath('phone-chat-card.png'),
		animations: 'disabled'
	});

	await page.getByRole('button', { name: 'Toggle Sidebar' }).click();
	const filterGroup = page.getByTestId('session-kind-filter');
	await expect(filterGroup).toBeVisible();
	await expect
		.poll(async () => {
			const box = await filterGroup.boundingBox();
			return box ? box.x >= 0 && box.x + box.width <= 360 : false;
		})
		.toBe(true);
	await page.screenshot({
		path: test.info().outputPath('phone-sidebar-filter.png'),
		animations: 'disabled'
	});

	await allowTeardownAborts(['/api/sync/status'], () => page.goto('/session/new?mode=chat'));
	const kindToggle = page.getByTestId('session-kind-toggle');
	await expect(kindToggle).toBeVisible();
	const toggleBox = (await kindToggle.boundingBox())!;
	expect(toggleBox.x).toBeGreaterThanOrEqual(0);
	expect(toggleBox.x + toggleBox.width).toBeLessThanOrEqual(360);
	await page.screenshot({
		path: test.info().outputPath('phone-new-chat.png'),
		animations: 'disabled'
	});

	// Return to desktop viewport and click "Start teaching →" on the Launch Card.
	await page.setViewportSize({ width: 1280, height: 800 });
	await allowTeardownAborts(['/api/sync/status'], () => page.goto(`/session/${chatId}`));
	await expect(card).toBeVisible();
	await card.getByTestId('prepare-session-start').click();
	await expect(page).toHaveURL(new RegExp(`/session/(?!new|${chatId})[^/]+$`));

	// The new Teaching session starts with the seeded Graph context and runs the Prober opening turn.
	await expect(page.getByTestId('phase-chip')).toHaveAttribute('data-phase', 'probe');
	await expect(page.getByTestId('graph-context-card')).toContainText('1 proposition');
	await expect(
		page.getByText('What does the slope of a secant line between two points')
	).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('launched-teaching.png'),
		animations: 'disabled'
	});

	// Settings → Prompts shows the Chat section alongside Teacher, Prober, Practice, and Shared.
	await allowTeardownAborts(['/api/sync/status'], () => page.goto('/settings?section=prompts'));
	for (const section of ['teacher', 'prober', 'practice', 'chat', 'shared']) {
		await expect(page.getByTestId(`prompt-section-${section}`)).toBeVisible();
	}
	await expect(page.getByTestId('prompt-row-chat/00-base.md')).toBeVisible();
	await expect(page.getByTestId('prompt-row-chat/10-tools.md')).toBeVisible();
});
