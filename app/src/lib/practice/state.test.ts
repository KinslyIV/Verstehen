import { expect, test } from 'vitest';
import type { Entry } from '#lib/api/client.js';
import {
	activeProblemOf,
	hasProblemCall,
	hasProblemPose,
	modelSolutionForConclude,
	pendingProblemDismissalOf,
	problemInputForConclude
} from './state.js';
import { ack, call, conclude, dismissed, pose, problemArguments } from './practice-fixtures.js';

test('a_cleanly_posed_problem_is_active_until_concluded_or_dismissed', () => {
	expect(activeProblemOf([])).toBeUndefined();
	expect(activeProblemOf(pose())).toEqual({
		toolCallId: 'p1',
		statement: 'Differentiate $x^2$.'
	});
	expect(activeProblemOf([...pose(), ...conclude()])).toBeUndefined();
	expect(activeProblemOf([...pose(), dismissed()])).toBeUndefined();
	expect(activeProblemOf([...pose('p1'), ...conclude(), ...pose('p2')])?.toolCallId).toBe('p2');
});

test('an_errored_or_unanswered_pose_is_not_active', () => {
	expect(activeProblemOf([call('p1', 'problem', problemArguments)])).toBeUndefined();
	expect(
		activeProblemOf([
			call('p1', 'problem', problemArguments),
			ack('p1', 'problem', { is_error: true })
		])
	).toBeUndefined();
});

test('stringified_pose_arguments_are_read', () => {
	const entries = [call('p1', 'problem', JSON.stringify(problemArguments)), ack('p1', 'problem')];
	expect(activeProblemOf(entries)?.statement).toBe(problemArguments.statement);
});

test('a_dismissal_awaits_its_conclude_until_a_later_clean_call', () => {
	expect(pendingProblemDismissalOf([...pose(), dismissed('p1')])).toBe('p1');
	expect(pendingProblemDismissalOf(pose())).toBeUndefined();
	const synthesized = [call('c', 'conclude', { outcome: 'dismissed' }), ack('c', 'conclude')];
	expect(pendingProblemDismissalOf([...pose(), dismissed(), ...synthesized])).toBeUndefined();
});

test('the_model_solution_comes_from_the_pose_before_the_conclude', () => {
	const entries: Entry[] = [...pose('p1'), ...conclude('c1'), ...pose('p2'), ...conclude('c2')];
	expect(problemInputForConclude(entries, 'c2')?.target).toEqual(['n1']);
	expect(modelSolutionForConclude(entries, 'c1')).toBe('The derivative is $2x$.');
	expect(modelSolutionForConclude(entries, 'missing')).toBeUndefined();
});

test('only_a_clean_pose_ack_counts_as_a_pose', () => {
	expect(hasProblemPose([ack('p1', 'problem')])).toBe(true);
	expect(hasProblemPose([ack('p1', 'problem', { details: { x: 1 } })])).toBe(false);
	expect(hasProblemPose([ack('p1', 'problem', { is_error: true })])).toBe(false);
	expect(hasProblemCall(pose())).toBe(true);
	expect(hasProblemCall([])).toBe(false);
});
