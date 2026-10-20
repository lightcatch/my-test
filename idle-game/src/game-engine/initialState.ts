import { recipes } from '../data/recipes';
import { zones } from '../data/zones';
import type { GameState } from './types';

export const SAVE_VERSION = 1;

export function createInitialState(now = Date.now()): GameState {
  const baseHealth = 42;
  return {
    schemaVersion: SAVE_VERSION,
    savedAt: now,
    lastActiveAt: now,
    player: {
      level: 1,
      experience: 0,
      experienceToNext: 30,
      gold: 12,
      health: baseHealth,
      maxHealth: baseHealth,
      baseStats: { attack: 5, defense: 2, health: baseHealth, speed: 0 },
      potions: { minorPotion: 2 }
    },
    materials: {
      wood: 14,
      fish: 8,
      ore: 8,
      slimeGel: 6,
      fang: 0,
      cloth: 0,
      crystal: 0
    },
    equipment: [],
    equipped: {},
    activities: {
      combat: { status: 'idle', enemyHp: 0, enemyMaxHp: 0, heroHealthAtStart: baseHealth, heroHitsDone: 0, enemyHitsDone: 0 },
      gathering: { status: 'idle', autoRepeat: false },
      crafting: { status: 'idle', autoRepeat: false }
    },
    unlocks: {
      zones: zones.filter((zone) => zone.unlockLevel <= 1).map((zone) => zone.id),
      recipes: recipes.filter((recipe) => recipe.unlockLevel <= 1).map((recipe) => recipe.id),
      automations: []
    },
    eventLog: [{ id: `welcome-${now}`, at: now, message: '篝火已经点亮。选择一项行动开始积累第一批资源。', tone: 'info' }]
  };
}
