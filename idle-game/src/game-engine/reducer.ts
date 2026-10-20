import { gatheringConfigs } from '../data/materials';
import { getInventoryLimit, canCraftRecipe, completeRecipe, dismantleEquipment } from './crafting';
import { startBattle } from './combat';
import { advance } from './simulation';
import type { EquipmentItem, GameCommand, GameState, RandomSource, TransitionResult } from './types';
import {
  addLog,
  allAutomationUnlocked,
  calculateRepairCost,
  cloneState,
  deductCosts,
  getRecipe,
  getTemplate,
  getZone,
  hasAutomation,
  pauseOtherActivities,
  refreshPlayerStats,
  shiftPausedActivity,
  slotLabel
} from './utils';

const err = (state: GameState, message: string): TransitionResult => ({ state, messages: [], error: message });

function checkParallel(state: GameState, now: number, activity: 'combat' | 'gathering' | 'crafting'): void {
  pauseOtherActivities(state, activity, now);
}

function startGathering(state: GameState, targetId: keyof typeof gatheringConfigs, automated: boolean, now: number): string | undefined {
  const config = gatheringConfigs[targetId];
  if (automated && !hasAutomation(state, config.automationId)) return '尚未建成对应自动化设施。';
  checkParallel(state, now, 'gathering');
  const current = state.activities.gathering;
  if (current.status === 'paused' && current.targetId === targetId) {
    shiftPausedActivity(current, now);
    current.status = 'running';
    current.autoRepeat = automated;
    return undefined;
  }
  state.activities.gathering = {
    status: 'running',
    targetId,
    startedAt: now,
    completeAt: now + config.durationMs,
    autoRepeat: automated
  };
  addLog(state, automated ? `${config.name}自动循环已启动。` : `${config.name}已开始。`, 'info', now);
  return undefined;
}

function startCrafting(state: GameState, recipeId: string, automated: boolean, now: number): string | undefined {
  const recipe = getRecipe(recipeId);
  if (!recipe) return '配方不存在。';
  if (automated && !hasAutomation(state, 'autoWorkshop')) return '尚未建成自动工坊。';
  const current = state.activities.crafting;
  if (current.status === 'paused' && current.recipeId === recipeId) {
    checkParallel(state, now, 'crafting');
    shiftPausedActivity(current, now);
    current.status = 'running';
    current.autoRepeat = automated;
    addLog(state, `${recipe.name}已恢复。`, 'info', now);
    return undefined;
  }
  const recipeError = canCraftRecipe(state, recipe);
  if (recipeError) return recipeError;
  checkParallel(state, now, 'crafting');
  deductCosts(state, recipe.costs);
  state.activities.crafting = {
    status: 'running',
    recipeId,
    startedAt: now,
    completeAt: now + recipe.durationMs,
    autoRepeat: automated
  };
  addLog(state, automated ? `${recipe.name}自动循环已启动。` : `${recipe.name}已开始。`, 'info', now);
  return undefined;
}

function repairItem(state: GameState, item: EquipmentItem, now: number): string | undefined {
  const cost = calculateRepairCost(item);
  if (item.currentDurability >= item.maxDurability) return '该装备无需修理。';
  if (state.player.gold < cost.gold || (state.materials[cost.materialId] ?? 0) < cost.material) return '金币或材料不足，无法修理。';
  state.player.gold -= cost.gold;
  state.materials[cost.materialId] -= cost.material;
  item.currentDurability = item.maxDurability;
  const template = getTemplate(item.templateId);
  addLog(state, `修理完成：${template?.name ?? '装备'}。`, 'success', now);
  return undefined;
}

export function applyCommand(source: GameState, command: GameCommand, now: number, rng: RandomSource): TransitionResult {
  const advanced = advance(source, now, rng).state;
  const state = cloneState(advanced);

  switch (command.type) {
    case 'startCombat': {
      const zone = getZone(command.zoneId);
      if (!zone || !state.unlocks.zones.includes(command.zoneId)) return err(state, '区域尚未解锁。');
      if (state.player.health <= 0) return err(state, '请先恢复生命。');
      checkParallel(state, now, 'combat');
      const current = state.activities.combat;
      if (current.status === 'paused' && current.zoneId === command.zoneId) {
        shiftPausedActivity(current, now);
        current.status = 'running';
      } else {
        startBattle(state, command.zoneId, now);
      }
      addLog(state, `进入 ${zone.name}，目标：${zone.enemy.name}。`, 'info', now);
      break;
    }
    case 'pauseCombat': {
      const activity = state.activities.combat;
      if (activity.status === 'running') {
        activity.status = 'paused';
        activity.pausedAt = now;
        addLog(state, '战斗已暂停。', 'info', now);
      }
      break;
    }
    case 'retreat': {
      state.activities.combat = { status: 'idle', enemyHp: 0, enemyMaxHp: 0, heroHealthAtStart: state.player.health, heroHitsDone: 0, enemyHitsDone: 0 };
      addLog(state, '已撤离战斗区域，开始缓慢恢复生命。', 'info', now);
      break;
    }
    case 'startGathering': {
      const message = startGathering(state, command.targetId, Boolean(command.automated), now);
      if (message) return err(state, message);
      break;
    }
    case 'pauseGathering': {
      const activity = state.activities.gathering;
      if (activity.status === 'running') {
        activity.status = 'paused';
        activity.pausedAt = now;
        addLog(state, '采集已暂停。', 'info', now);
      }
      break;
    }
    case 'startCrafting': {
      const message = startCrafting(state, command.recipeId, Boolean(command.automated), now);
      if (message) return err(state, message);
      break;
    }
    case 'pauseCrafting': {
      const activity = state.activities.crafting;
      if (activity.status === 'running') {
        activity.status = 'paused';
        activity.pausedAt = now;
        addLog(state, '制作已暂停。', 'info', now);
      }
      break;
    }
    case 'equipItem': {
      const item = state.equipment.find((entry) => entry.instanceId === command.instanceId);
      if (!item) return err(state, '装备不存在。');
      const template = getTemplate(item.templateId);
      if (!template) return err(state, '装备模板不存在。');
      state.equipped[template.slot] = item.instanceId;
      refreshPlayerStats(state, true);
      addLog(state, `装备了 ${template.name}。`, 'success', now);
      break;
    }
    case 'unequipItem': {
      if (!state.equipped[command.slot]) return err(state, `当前没有装备${slotLabel(command.slot)}。`);
      delete state.equipped[command.slot];
      refreshPlayerStats(state);
      addLog(state, `卸下了${slotLabel(command.slot)}。`, 'info', now);
      break;
    }
    case 'usePotion': {
      if (state.player.potions.minorPotion <= 0) return err(state, '没有可用的微光药水。');
      if (state.player.health >= state.player.maxHealth) return err(state, '生命已满。');
      state.player.potions.minorPotion -= 1;
      const healed = Math.max(1, Math.floor(state.player.maxHealth * 0.25));
      state.player.health = Math.min(state.player.maxHealth, state.player.health + healed);
      addLog(state, `饮下微光药水，恢复 ${healed} 点生命。`, 'success', now);
      break;
    }
    case 'repairItem': {
      const item = state.equipment.find((entry) => entry.instanceId === command.instanceId);
      if (!item) return err(state, '装备不存在。');
      const message = repairItem(state, item, now);
      if (message) return err(state, message);
      refreshPlayerStats(state);
      break;
    }
    case 'repairAll': {
      const targets = state.equipment.filter((item) => item.currentDurability < item.maxDurability);
      if (targets.length === 0) return err(state, '没有需要修理的装备。');
      const snapshot = cloneState(state);
      for (const item of targets) {
        const message = repairItem(state, item, now);
        if (message) return err(snapshot, '金币或材料不足，无法一键修理全部装备。');
      }
      refreshPlayerStats(state);
      break;
    }
    case 'dismantleItem': {
      const message = dismantleEquipment(state, command.instanceId, now);
      if (message) return err(state, message);
      break;
    }
    case 'enableAutomation': {
      if (!state.unlocks.automations.includes(command.automationId)) return err(state, '请先制作对应自动化设施。');
      addLog(state, '自动化设施已可使用。', 'info', now);
      break;
    }
  }

  state.savedAt = now;
  state.lastActiveAt = now;
  return { state, messages: [] };
}

export function getActivitySummary(state: GameState): string {
  const running = ['combat', 'gathering', 'crafting'].filter((type) => state.activities[type as keyof GameState['activities']].status === 'running');
  if (!running.length) return '未进行活动';
  const labels = { combat: '战斗', gathering: '采集', crafting: '制作' };
  return running.map((type) => labels[type as keyof typeof labels]).join(' / ');
}

export const inventoryLimit = getInventoryLimit;
