import { zones } from '../data/zones';
import type { GameState, RandomSource, Stats } from './types';
import { grantExperience } from './progression';
import { addLog, addMaterial, getEffectiveStats, getEquippedItems, getZone, refreshPlayerStats, rollInt } from './utils';

const MIN_INTERVAL = 500;
const MAX_BATTLE_EVENTS = 60_000;

export function attackIntervalMs(speed: number): number {
  return Math.max(MIN_INTERVAL, 2500 / Math.max(0.1, 1 + speed / 100));
}

export function damage(attack: number, defense: number): number {
  return Math.max(1, attack - defense);
}

export function startBattle(state: GameState, zoneId: string, now: number): void {
  const zone = getZone(zoneId);
  if (!zone) return;
  const heroStats = getEffectiveStats(state);
  state.activities.combat = {
    status: 'running',
    zoneId,
    battleId: `${zoneId}-${now}`,
    enemyHp: zone.enemy.stats.health,
    enemyMaxHp: zone.enemy.stats.health,
    battleStartedAt: now,
    heroHealthAtStart: state.player.health,
    nextHeroAttackAt: now + attackIntervalMs(heroStats.speed),
    nextEnemyAttackAt: now + attackIntervalMs(zone.enemy.stats.speed),
    heroHitsDone: 0,
    enemyHitsDone: 0
  };
}

function reduceDurability(state: GameState): void {
  for (const item of getEquippedItems(state)) item.currentDurability = Math.max(0, item.currentDurability - 1);
  refreshPlayerStats(state);
}

function rewardVictory(state: GameState, zoneId: string, at: number, rng: RandomSource): void {
  const zone = getZone(zoneId);
  if (!zone) return;
  state.player.gold += zone.gold;
  grantExperience(state, zone.experience, at);
  const materials: string[] = [];
  for (const entry of zone.drops) {
    const chance = Math.round((entry.chance ?? 1) * 100);
    if (rollInt(rng, 1, 100) <= chance) {
      const amount = rollInt(rng, entry.min, entry.max);
      addMaterial(state, entry.materialId, amount);
      materials.push(`${amount} ${entry.materialId}`);
    }
  }
  addLog(state, `击败 ${zone.enemy.name}，获得 ${zone.experience} 经验、${zone.gold} 金币${materials.length ? `、${materials.join('、')}` : ''}。`, 'success', at);
}

function beginNextBattle(state: GameState, at: number): void {
  const activity = state.activities.combat;
  if (!activity.zoneId) return;
  const zone = getZone(activity.zoneId);
  if (!zone) return;
  const heroStats = getEffectiveStats(state);
  activity.enemyHp = zone.enemy.stats.health;
  activity.enemyMaxHp = zone.enemy.stats.health;
  activity.battleId = `${zone.id}-${at}`;
  activity.battleStartedAt = at;
  activity.heroHealthAtStart = state.player.health;
  activity.nextHeroAttackAt = at + attackIntervalMs(heroStats.speed);
  activity.nextEnemyAttackAt = at + attackIntervalMs(zone.enemy.stats.speed);
  activity.heroHitsDone = 0;
  activity.enemyHitsDone = 0;
}

function finishVictory(state: GameState, at: number, rng: RandomSource): void {
  const activity = state.activities.combat;
  if (!activity.zoneId) return;
  const zone = getZone(activity.zoneId);
  if (!zone) return;
  rewardVictory(state, activity.zoneId, at, rng);
  reduceDurability(state);
  if (getEquippedItems(state).some((item) => item.currentDurability === 0)) {
    addLog(state, '装备出现破损，已切换为保护属性，战斗继续。', 'warning', at);
  }
  beginNextBattle(state, at);
}

function finishDefeat(state: GameState, at: number): void {
  const activity = state.activities.combat;
  state.player.health = 1;
  reduceDurability(state);
  activity.status = 'blocked';
  activity.blockedReason = '勇士倒下了。脱战恢复生命或使用药水后再出发。';
  addLog(state, '勇士倒下，生命降为 1，当前战斗已停止。', 'danger', at);
}

export function processCombat(state: GameState, now: number, rng: RandomSource): void {
  const activity = state.activities.combat;
  if (activity.status !== 'running' || !activity.zoneId) return;
  const zone = getZone(activity.zoneId);
  if (!zone || !activity.nextHeroAttackAt || !activity.nextEnemyAttackAt) return;

  let events = 0;
  while (activity.status === 'running' && events++ < MAX_BATTLE_EVENTS) {
    const eventAt = Math.min(activity.nextHeroAttackAt ?? Infinity, activity.nextEnemyAttackAt ?? Infinity);
    if (eventAt > now) break;
    const heroActs = (activity.nextHeroAttackAt ?? Infinity) <= (activity.nextEnemyAttackAt ?? Infinity);
    const heroStats = getEffectiveStats(state);

    if (heroActs) {
      activity.enemyHp = Math.max(0, activity.enemyHp - damage(heroStats.attack, zone.enemy.stats.defense));
      activity.heroHitsDone += 1;
      activity.nextHeroAttackAt = eventAt + attackIntervalMs(heroStats.speed);
      if (activity.enemyHp <= 0) {
        finishVictory(state, eventAt, rng);
        continue;
      }
    } else {
      state.player.health = Math.max(0, state.player.health - damage(zone.enemy.stats.attack, heroStats.defense));
      activity.enemyHitsDone += 1;
      activity.nextEnemyAttackAt = eventAt + attackIntervalMs(zone.enemy.stats.speed);
      if (state.player.health <= 0) {
        finishDefeat(state, eventAt);
        continue;
      }
    }
  }
  if (events >= MAX_BATTLE_EVENTS && activity.status === 'running') {
    activity.status = 'blocked';
    activity.blockedReason = '本次结算事件过多，请再次刷新继续。';
    addLog(state, '战斗结算达到安全上限，已暂停。', 'warning', now);
  }
}

export function getZoneForDisplay(zoneId?: string) {
  return zones.find((zone) => zone.id === zoneId);
}

export function enemyDamagePreview(heroStats: Stats, zoneId: string): number {
  const zone = getZone(zoneId);
  return zone ? damage(zone.enemy.stats.attack, heroStats.defense) : 0;
}
