import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { userEvent } from 'vitest/browser';
import Pair from './pair/+page.svelte';
import './layout.css';

const { goto, loadConnection, pairDevice } = vi.hoisted(() => ({
	goto: vi.fn(async () => {}),
	loadConnection: vi.fn(async (): Promise<Record<string, string>> => ({})),
	pairDevice: vi.fn()
}));

vi.mock('$app/navigation', () => ({ goto }));
vi.mock('#lib/api/connection.js', () => ({ loadConnection }));
vi.mock('#lib/api/client.js', () => ({ pairDevice }));

beforeEach(() => {
	goto.mockClear();
	loadConnection.mockResolvedValue({});
	pairDevice.mockReset();
});

test('pair_waits_for_an_address_an_eight_character_code_and_a_name', async () => {
	const screen = await render(Pair);
	const pair = screen.getByRole('button', { name: 'Pair' });
	await expect.element(screen.getByLabelText('Device name')).toHaveValue('Phone');
	await expect.element(pair).toBeDisabled();
	await userEvent.fill(screen.getByLabelText('Server address'), '100.64.0.7:8420');
	await userEvent.fill(screen.getByLabelText('Pairing code'), 'ABCD234');
	await expect.element(pair).toBeDisabled();
	await userEvent.fill(screen.getByLabelText('Pairing code'), 'ABCD2345');
	await expect.element(pair).toBeEnabled();
});

test('pair_sends_the_form_and_opens_the_lesson_screen', async () => {
	pairDevice.mockResolvedValue({});
	const screen = await render(Pair);
	await userEvent.fill(screen.getByLabelText('Server address'), '100.64.0.7:8420');
	await userEvent.fill(screen.getByLabelText('Pairing code'), 'abcd2345');
	await userEvent.click(screen.getByRole('button', { name: 'Pair' }));
	await expect.poll(() => goto.mock.calls.length).toBe(1);
	expect(pairDevice).toHaveBeenCalledWith('100.64.0.7:8420', 'abcd2345', 'Phone');
	expect(goto).toHaveBeenCalledWith('/');
});

test('pair_shows_the_failure_and_keeps_the_form_editable', async () => {
	pairDevice.mockRejectedValue(new Error('That code is invalid or has expired.'));
	const screen = await render(Pair);
	await userEvent.fill(screen.getByLabelText('Server address'), '100.64.0.7:8420');
	await userEvent.fill(screen.getByLabelText('Pairing code'), 'ABCD2345');
	await userEvent.click(screen.getByRole('button', { name: 'Pair' }));
	await expect
		.element(screen.getByRole('alert'))
		.toHaveTextContent('That code is invalid or has expired.');
	expect(goto).not.toHaveBeenCalled();
	await expect.element(screen.getByRole('button', { name: 'Pair' })).toBeEnabled();
});

test('pair_prefills_the_remembered_server_address', async () => {
	loadConnection.mockResolvedValue({ server_url: 'http://100.64.0.7:8420' });
	const screen = await render(Pair);
	await expect.element(screen.getByLabelText('Server address')).toHaveValue('100.64.0.7:8420');
});
