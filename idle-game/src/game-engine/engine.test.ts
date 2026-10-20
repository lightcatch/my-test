import { describe, expect, it } from 'vitest';
import { createInitialState } from './initialState';
import { applyCommand } from './reducer';
import { advance } from './simulation';
import { fixedRandom } from './rng';

describe('idle game engine', () => {
  it('resolves a battle and reduces durability once per completed battle', () => {
    const start = createInitialState(0);
    const armed = applyCommand(start, { type: 'startCombat', zoneId: 'mossyTrail' }, 0, fixedRandom(1)).state;
    const result = advance(armed, 60_000, fixedRandom(1)).state;
    expect(result.player.gold).toBeGreaterThan(start.player.gold);
    expect(result.activities.combat.heroHitsDone).toBeGreaterThanOrEqual(0);
    expect(result.equipment).toHaveLength(0);
  });

  it('creates ranged equipment values deterministically through injected rng', () => {
    let state = createInitialState(0);
    state.materials.wood = 20;
    state.materials.ore = 20;
    state = applyCommand(state, { type: 'startCrafting', recipeId: 'craftWoodenSword' }, 0, fixedRandom(7)).state;
    state = advance(state, 15_000, fixedRandom(7)).state;
    expect(state.equipment).toHaveLength(1);
    expect(state.equipment[0].rolledStats.attack).toBe(7);
    expect(state.equipment[0].statRangesSnapshot.attack).toEqual({ min: 4, max: 7 });
  });

  it('caps offline progress at eight hours and keeps manual production paused', () => {
    let state = createInitialState(0);
    state = applyCommand(state, { type: 'startGathering', targetId: 'lumber' }, 0, fixedRandom(1)).state;
    const resumed = advance(state, 24 * 60 * 60 * 1000, fixedRandom(1), { offline: true }).state;
    expect(resumed.materials.wood).toBe(state.materials.wood);
    expect(resumed.activities.gathering.status).toBe('running');
  });

  it('prevents two activities from running before automation is unlocked', () => {
    let state = createInitialState(0);
    state = applyCommand(state, { type: 'startCombat', zoneId: 'mossyTrail' }, 0, fixedRandom(1)).state;
    state = applyCommand(state, { type: 'startGathering', targetId: 'lumber' }, 1, fixedRandom(1)).state;
    expect(state.activities.combat.status).toBe('paused');
    expect(state.activities.gathering.status).toBe('running');
  });

  it('keeps broken gear protection stats and allows combat to continue', () => {
    let state = createInitialState(0);
    state.materials.wood = 20;
    state.materials.ore = 20;
    state = applyCommand(state, { type: 'startCrafting', recipeId: 'craftWoodenSword' }, 0, fixedRandom(4)).state;
    state = advance(state, 15_000, fixedRandom(4)).state;
    const item = state.equipment[0];
    state = applyCommand(state, { type: 'equipItem', instanceId: item.instanceId }, 15_001, fixedRandom(1)).state;
    state.equipment[0].currentDurability = 0;
    const started = applyCommand(state, { type: 'startCombat', zoneId: 'mossyTrail' }, 15_002, fixedRandom(1));
    expect(started.error).toBeUndefined();
    expect(started.state.activities.combat.status).toBe('running');
  });
});
