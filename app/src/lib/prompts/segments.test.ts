import { expect, test } from 'vitest';
import type { PromptSegment, PromptSegments } from '#lib/api/client.js';
import { sectionedSegments, segmentName } from './segments.js';

const segment = (path: string, shared = false): PromptSegment => ({
	path,
	source_text: `source of ${path}`,
	override_text: null,
	enabled: false,
	shared
});

test('segment_names_drop_the_number_prefix_and_extension', () => {
	expect(segmentName('teacher/20-teaching.md')).toBe('Teaching');
	expect(segmentName('system-prompt.md')).toBe('System prompt');
	expect(segmentName('shared/16-mental-model.md')).toBe('Mental model');
});

test('segment_names_drop_leading_digits_and_dashes_and_turn_dashes_into_spaces', () => {
	expect(segmentName('practice/00-base.md')).toBe('Base');
	expect(segmentName('x/05-a-b--c.md')).toBe('A b c');
	expect(segmentName('prober/10-probe-doctrine.md')).toBe('Probe doctrine');
	expect(segmentName('plain.md')).toBe('Plain');
});

test('sections_list_each_agent_then_shared_fragments_once_with_their_users', () => {
	const view: PromptSegments = {
		teacher: [
			segment('system-prompt.md', true),
			segment('teacher/20-teaching.md'),
			segment('shared/10-voice.md', true),
			segment('shared/20-question-tools.md', true)
		],
		prober: [
			segment('system-prompt.md', true),
			segment('prober/10-probe-doctrine.md'),
			segment('shared/10-voice.md', true),
			segment('shared/20-question-tools.md', true)
		],
		practice: [segment('practice/00-base.md'), segment('shared/10-voice.md', true)],
		chat: [segment('chat/00-base.md'), segment('shared/10-voice.md', true)]
	};
	const sections = sectionedSegments(view);
	expect(sections.map((section) => [section.id, section.segments.map((s) => s.path)])).toEqual([
		['teacher', ['teacher/20-teaching.md']],
		['prober', ['prober/10-probe-doctrine.md']],
		['practice', ['practice/00-base.md']],
		['chat', ['chat/00-base.md']],
		['shared', ['system-prompt.md', 'shared/10-voice.md', 'shared/20-question-tools.md']]
	]);
	expect(sections[4].segments.map((s) => s.usage)).toEqual([
		'Used by Teacher and Prober',
		'Used by Teacher, Prober, Practice and Chat',
		'Used by Teacher and Prober'
	]);
});
