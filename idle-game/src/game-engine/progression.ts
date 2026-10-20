import { recipes } from '../data/recipes';
import { zones } from '../data/zones';
import type { GameState } from './types';
import { addLog, refreshPlayerStats } from './utils';

export function grantExperience(state: GameState, amount: number, at: number): void {
  state.player.experience += amount;
  let leveled = false;
  while (state.player.experience >= state.player.experienceToNext) {
    state.player.experience -= state.player.experienceToNext;
    state.player.level += 1;
    state.player.experienceToNext = Math.floor(30 * Math.pow(1.34, state.player.level - 1));
    state.player.baseStats.attack += 2;
    state.player.baseStats.defense += 1;
    state.player.baseStats.health += 6;
    leveled = true;
    addLog(state, `升至 ${state.player.level} 级：攻击 +2，防御 +1，生命 +6。`, 'success', at);
  }
  if (leveled) refreshPlayerStats(state, true);
  if (leveled) unlockAvailableContent(state, at);
}

export function unlockAvailableContent(state: GameState, at: number): void {
  for (const zone of zones) {
    if (zone.unlockLevel <= state.player.level && !state.unlocks.zones.includes(zone.id)) {
      state.unlocks.zones.push(zone.id);
      addLog(state, `新区域已解锁：${zone.name}。`, 'success', at);
    }
  }
  for (const recipe of recipes) {
    if (recipe.unlockLevel <= state.player.level && !state.unlocks.recipes.includes(recipe.id)) {
      state.unlocks.recipes.push(recipe.id);
      addLog(state, `新配方已解锁：${recipe.name}。`, 'success', at);
    }
  }
}
