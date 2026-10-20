import { equipmentTemplates } from '../data/equipment';
import { recipes } from '../data/recipes';
import type { EquipmentItem, GameState, RandomSource, RecipeConfig } from './types';
import { addLog, addMaterial, getRecipe, getTemplate, hasCosts, rollInt } from './utils';

const INVENTORY_LIMIT = 12;

export function createEquipment(templateId: string, now: number, rng: RandomSource): EquipmentItem | undefined {
  const template = getTemplate(templateId);
  if (!template) return undefined;
  const rolledStats: EquipmentItem['rolledStats'] = {};
  for (const [stat, range] of Object.entries(template.statRanges) as Array<[keyof EquipmentItem['rolledStats'], { min: number; max: number }]>) {
    rolledStats[stat] = rollInt(rng, range.min, range.max);
  }
  return {
    instanceId: `${template.id}-${now}-${rollInt(rng, 1000, 9999)}`,
    templateId: template.id,
    rolledStats,
    statRangesSnapshot: structuredClone(template.statRanges),
    currentDurability: template.durability,
    maxDurability: template.durability,
    createdAt: now
  };
}

export function canCraftRecipe(state: GameState, recipe: RecipeConfig): string | undefined {
  if (!state.unlocks.recipes.includes(recipe.id)) return '配方尚未解锁。';
  if (!hasCosts(state, recipe.costs)) return '材料不足。';
  if (recipe.output.kind === 'equipment' && state.equipment.length >= INVENTORY_LIMIT) return '装备栏已满，请先分解装备。';
  if (recipe.output.kind === 'automation' && state.unlocks.automations.includes(recipe.output.automationId)) return '设施已建成。';
  return undefined;
}

export function completeRecipe(state: GameState, recipeId: string, now: number, rng: RandomSource): string | undefined {
  const recipe = getRecipe(recipeId);
  if (!recipe) return '配方不存在。';
  if (recipe.output.kind === 'equipment') {
    if (state.equipment.length >= INVENTORY_LIMIT) return '装备栏已满，请先分解装备。';
    const item = createEquipment(recipe.output.templateId, now, rng);
    if (!item) return '装备模板不存在。';
    state.equipment.push(item);
    const template = getTemplate(item.templateId)!;
    const values = Object.entries(item.rolledStats).map(([stat, value]) => `${stat} +${value}`).join('，');
    addLog(state, `制作完成：${template.name}（${values}）。`, 'success', now);
  }
  if (recipe.output.kind === 'potion') {
    state.player.potions[recipe.output.potionId] = (state.player.potions[recipe.output.potionId] ?? 0) + recipe.output.amount;
    addLog(state, `制作完成：微光药水 x${recipe.output.amount}。`, 'success', now);
  }
  if (recipe.output.kind === 'automation') {
    if (!state.unlocks.automations.includes(recipe.output.automationId)) state.unlocks.automations.push(recipe.output.automationId);
    addLog(state, `设施建成：${recipe.name.replace('制作', '')}。`, 'success', now);
  }
  return undefined;
}

export function dismantleEquipment(state: GameState, instanceId: string, now: number): string | undefined {
  const index = state.equipment.findIndex((item) => item.instanceId === instanceId);
  if (index === -1) return '装备不存在。';
  const item = state.equipment[index];
  if (Object.values(state.equipped).includes(instanceId)) return '请先卸下已装备的物品。';
  const template = getTemplate(item.templateId);
  if (!template) return '装备模板不存在。';
  const materialId = template.slot === 'accessory' ? 'fish' : template.slot === 'armor' ? 'cloth' : 'ore';
  const amount = Math.max(1, template.tier * 2);
  state.equipment.splice(index, 1);
  addMaterial(state, materialId, amount);
  addLog(state, `分解 ${template.name}，获得 ${amount} ${materialId}。`, 'info', now);
  return undefined;
}

export const getInventoryLimit = () => INVENTORY_LIMIT;
export const getRecipeList = () => recipes;
export const getEquipmentTemplates = () => equipmentTemplates;
