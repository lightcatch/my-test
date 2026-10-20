import { equipmentTemplates } from '../data/equipment';
import { recipes } from '../data/recipes';
import { zones } from '../data/zones';
import type {
  ActivityType,
  EquipmentItem,
  EquipmentSlot,
  GameEvent,
  GameState,
  MaterialId,
  Stats,
  AutomationId
} from './types';

export const OFFLINE_CAP_MS = 8 * 60 * 60 * 1000;
export const MAX_LOG_ITEMS = 80;

export const cloneState = (state: GameState): GameState => structuredClone(state);

export function getTemplate(templateId: string) {
  return equipmentTemplates.find((item) => item.id === templateId);
}

export function getRecipe(recipeId: string) {
  return recipes.find((item) => item.id === recipeId);
}

export function getZone(zoneId: string) {
  return zones.find((item) => item.id === zoneId);
}

export function addLog(state: GameState, message: string, tone: GameEvent['tone'], at: number): GameEvent {
  const event = { id: `${at}-${state.eventLog.length}-${Math.random().toString(36).slice(2, 7)}`, at, message, tone };
  state.eventLog = [event, ...state.eventLog].slice(0, MAX_LOG_ITEMS);
  return event;
}

export function getEquippedItems(state: GameState): EquipmentItem[] {
  return Object.values(state.equipped)
    .map((instanceId) => state.equipment.find((item) => item.instanceId === instanceId))
    .filter((item): item is EquipmentItem => Boolean(item));
}

export function getEffectiveStats(state: GameState): Stats {
  const result = { ...state.player.baseStats };
  for (const item of getEquippedItems(state)) {
    const template = getTemplate(item.templateId);
    if (!template) continue;
    const source = item.currentDurability > 0 ? item.rolledStats : template.brokenStats;
    for (const key of Object.keys(source) as Array<keyof Stats>) {
      result[key] += source[key] ?? 0;
    }
  }
  return result;
}

export function refreshPlayerStats(state: GameState, healDelta = false): void {
  const oldMax = state.player.maxHealth;
  const oldHealth = state.player.health;
  const nextMax = Math.max(1, getEffectiveStats(state).health);
  state.player.maxHealth = nextMax;
  const delta = nextMax - oldMax;
  state.player.health = Math.max(0, Math.min(nextMax, healDelta ? oldHealth + Math.max(0, delta) : oldHealth));
}

export function getRunningActivities(state: GameState): ActivityType[] {
  const result: ActivityType[] = [];
  if (state.activities.combat.status === 'running') result.push('combat');
  if (state.activities.gathering.status === 'running') result.push('gathering');
  if (state.activities.crafting.status === 'running') result.push('crafting');
  return result;
}

export function hasAutomation(state: GameState, automationId: AutomationId): boolean {
  return state.unlocks.automations.includes(automationId);
}

export function allAutomationUnlocked(state: GameState): boolean {
  return (['autoLumber', 'autoFishing', 'autoMining', 'autoWorkshop'] as AutomationId[]).every((id) => hasAutomation(state, id));
}

export function pauseOtherActivities(state: GameState, except: ActivityType, now: number): void {
  if (allAutomationUnlocked(state)) return;
  const activities: Array<[ActivityType, { status: 'idle' | 'running' | 'paused' | 'blocked'; pausedAt?: number }]> = [
    ['combat', state.activities.combat],
    ['gathering', state.activities.gathering],
    ['crafting', state.activities.crafting]
  ];
  for (const [type, activity] of activities) {
    if (type !== except && activity.status === 'running') {
      activity.status = 'paused';
      activity.pausedAt = now;
    }
  }
}

export function shiftPausedActivity(activity: { startedAt?: number; completeAt?: number; battleStartedAt?: number; nextHeroAttackAt?: number; nextEnemyAttackAt?: number; pausedAt?: number }, now: number): void {
  if (!activity.pausedAt) return;
  const delta = Math.max(0, now - activity.pausedAt);
  if ('completeAt' in activity && activity.completeAt !== undefined) activity.completeAt += delta;
  if ('startedAt' in activity && activity.startedAt !== undefined) activity.startedAt += delta;
  if ('battleStartedAt' in activity && activity.battleStartedAt !== undefined) activity.battleStartedAt += delta;
  if ('nextHeroAttackAt' in activity && activity.nextHeroAttackAt !== undefined) activity.nextHeroAttackAt += delta;
  if ('nextEnemyAttackAt' in activity && activity.nextEnemyAttackAt !== undefined) activity.nextEnemyAttackAt += delta;
  activity.pausedAt = undefined;
}

export function hasCosts(state: GameState, costs: Array<{ materialId: MaterialId; amount: number }>): boolean {
  return costs.every(({ materialId, amount }) => (state.materials[materialId] ?? 0) >= amount);
}

export function deductCosts(state: GameState, costs: Array<{ materialId: MaterialId; amount: number }>): void {
  for (const { materialId, amount } of costs) state.materials[materialId] = Math.max(0, (state.materials[materialId] ?? 0) - amount);
}

export function addMaterial(state: GameState, materialId: MaterialId, amount: number): void {
  state.materials[materialId] = Math.max(0, (state.materials[materialId] ?? 0) + amount);
}

export function calculateRepairCost(item: EquipmentItem): { gold: number; materialId: MaterialId; material: number } {
  const template = getTemplate(item.templateId);
  const tier = template?.tier ?? 1;
  const missing = Math.max(0, item.maxDurability - item.currentDurability);
  return { gold: Math.max(1, Math.ceil(missing * (0.8 + tier * 0.25))), materialId: template?.slot === 'armor' ? 'cloth' : 'ore', material: Math.max(1, Math.ceil(missing * 0.35)) };
}

export function rollInt(rng: { int(min: number, max: number): number }, min: number, max: number): number {
  return Math.max(min, Math.min(max, Math.trunc(rng.int(min, max))));
}

export function slotLabel(slot: EquipmentSlot): string {
  return { weapon: '武器', armor: '护甲', accessory: '饰品' }[slot];
}
