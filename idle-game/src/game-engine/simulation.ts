import { gatheringConfigs } from '../data/materials';
import { getRecipe } from './utils';
import { completeRecipe, canCraftRecipe } from './crafting';
import { processCombat } from './combat';
import type { GameState, RandomSource, SimulationResult } from './types';
import { OFFLINE_CAP_MS, addLog, addMaterial, cloneState, hasAutomation, rollInt } from './utils';

export interface AdvanceOptions {
  offline?: boolean;
}

function shiftTimedActivity(activity: { startedAt?: number; completeAt?: number }, delta: number): void {
  if (activity.startedAt !== undefined) activity.startedAt += delta;
  if (activity.completeAt !== undefined) activity.completeAt += delta;
}

function processGathering(state: GameState, now: number, rng: RandomSource, offline: boolean, offlineDelta: number): void {
  const activity = state.activities.gathering;
  if (activity.status !== 'running' || !activity.targetId || !activity.completeAt) return;
  const config = gatheringConfigs[activity.targetId];
  const offlineAllowed = activity.autoRepeat && hasAutomation(state, config.automationId);
  if (offline && !offlineAllowed) {
    shiftTimedActivity(activity, offlineDelta);
    return;
  }
  let loops = 0;
  while (activity.status === 'running' && activity.completeAt <= now && loops++ < 10_000) {
    const quantity = rollInt(rng, config.min, config.max);
    addMaterial(state, config.materialId, quantity);
    addLog(state, `${config.name}完成，获得 ${quantity} ${config.materialId}。`, 'success', activity.completeAt);
    if (!activity.autoRepeat) {
      state.activities.gathering = { status: 'idle', autoRepeat: false };
      return;
    }
    activity.startedAt = activity.completeAt;
    activity.completeAt += config.durationMs;
  }
}

function processCrafting(state: GameState, now: number, rng: RandomSource, offline: boolean, offlineDelta: number): void {
  const activity = state.activities.crafting;
  if (activity.status !== 'running' || !activity.recipeId || !activity.completeAt) return;
  const offlineAllowed = activity.autoRepeat && hasAutomation(state, 'autoWorkshop');
  if (offline && !offlineAllowed) {
    shiftTimedActivity(activity, offlineDelta);
    return;
  }
  let loops = 0;
  while (activity.status === 'running' && activity.completeAt <= now && loops++ < 10_000) {
    const recipe = getRecipe(activity.recipeId);
    if (!recipe) {
      state.activities.crafting = { status: 'blocked', autoRepeat: false, blockedReason: '配方不存在。' };
      return;
    }
    const error = completeRecipe(state, recipe.id, activity.completeAt, rng);
    if (error) {
      state.activities.crafting = { status: 'blocked', autoRepeat: false, blockedReason: error };
      addLog(state, `制作已停止：${error}`, 'warning', activity.completeAt);
      return;
    }
    if (!activity.autoRepeat || recipe.output.kind === 'automation') {
      state.activities.crafting = { status: 'idle', autoRepeat: false };
      return;
    }
    const nextError = canCraftRecipe(state, recipe);
    if (nextError) {
      state.activities.crafting = { status: 'blocked', autoRepeat: false, blockedReason: nextError };
      addLog(state, `自动制作已停止：${nextError}`, 'warning', activity.completeAt);
      return;
    }
    for (const cost of recipe.costs) state.materials[cost.materialId] -= cost.amount;
    activity.startedAt = activity.completeAt;
    activity.completeAt += recipe.durationMs;
  }
}

function passiveHealing(state: GameState, from: number, to: number): void {
  if (state.activities.combat.status === 'running') return;
  const ticks = Math.floor(Math.max(0, to - from) / 10_000);
  if (ticks <= 0 || state.player.health >= state.player.maxHealth) return;
  const perTick = Math.max(1, Math.floor(state.player.maxHealth * 0.01));
  state.player.health = Math.min(state.player.maxHealth, state.player.health + ticks * perTick);
}

export function advance(source: GameState, now: number, rng: RandomSource, options: AdvanceOptions = {}): SimulationResult {
  const state = cloneState(source);
  const previous = state.lastActiveAt;
  const limitedNow = options.offline ? Math.min(now, previous + OFFLINE_CAP_MS) : Math.max(previous, now);
  if (limitedNow <= previous) return { state, messages: [] };

  passiveHealing(state, previous, limitedNow);
  processCombat(state, limitedNow, rng);
  // Manual activities freeze while the page is closed, so shift their due time
  // by the full wall-clock gap before updating lastActiveAt.
  const offlineDelta = Boolean(options.offline) ? Math.max(0, now - previous) : 0;
  processGathering(state, limitedNow, rng, Boolean(options.offline), offlineDelta);
  processCrafting(state, limitedNow, rng, Boolean(options.offline), offlineDelta);
  state.lastActiveAt = now;
  state.savedAt = now;
  return { state, messages: [] };
}

export function getActivityProgress(state: GameState, type: 'gathering' | 'crafting', now: number): number {
  const activity = state.activities[type];
  if (!activity.startedAt || !activity.completeAt) return 0;
  return Math.max(0, Math.min(1, (now - activity.startedAt) / Math.max(1, activity.completeAt - activity.startedAt)));
}

export function canRunAutomaticGathering(state: GameState, targetId: keyof typeof gatheringConfigs): boolean {
  return hasAutomation(state, gatheringConfigs[targetId].automationId);
}
