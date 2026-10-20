import { z } from 'zod';

const statSchema = z.object({ attack: z.number(), defense: z.number(), health: z.number(), speed: z.number() });
const materialKeys = ['wood', 'fish', 'ore', 'slimeGel', 'fang', 'cloth', 'crystal'] as const;
const materialSchema = z.record(z.enum(materialKeys), z.number().nonnegative());
const equipmentSchema = z.object({
  instanceId: z.string(),
  templateId: z.string(),
  rolledStats: z.record(z.string(), z.number()),
  statRangesSnapshot: z.record(z.string(), z.object({ min: z.number(), max: z.number() })),
  currentDurability: z.number().nonnegative(),
  maxDurability: z.number().positive(),
  createdAt: z.number()
});
const statusSchema = z.enum(['idle', 'running', 'paused', 'blocked']);

export const saveSchema = z.object({
  schemaVersion: z.number().int().positive(),
  savedAt: z.number(),
  lastActiveAt: z.number(),
  player: z.object({
    level: z.number().int().positive(),
    experience: z.number().nonnegative(),
    experienceToNext: z.number().positive(),
    gold: z.number().nonnegative(),
    health: z.number().nonnegative(),
    maxHealth: z.number().positive(),
    baseStats: statSchema,
    potions: z.record(z.string(), z.number().int().nonnegative())
  }),
  materials: materialSchema,
  equipment: z.array(equipmentSchema).max(12),
  equipped: z.record(z.enum(['weapon', 'armor', 'accessory']), z.string()).optional().default({}),
  activities: z.object({
    combat: z.object({
      status: statusSchema,
      zoneId: z.string().optional(),
      battleId: z.string().optional(),
      enemyHp: z.number().nonnegative(),
      enemyMaxHp: z.number().nonnegative(),
      battleStartedAt: z.number().optional(),
      heroHealthAtStart: z.number().nonnegative(),
      nextHeroAttackAt: z.number().optional(),
      nextEnemyAttackAt: z.number().optional(),
      heroHitsDone: z.number().int().nonnegative(),
      enemyHitsDone: z.number().int().nonnegative(),
      pausedAt: z.number().optional(),
      blockedReason: z.string().optional()
    }),
    gathering: z.object({ status: statusSchema, targetId: z.enum(['lumber', 'fishing', 'mining']).optional(), startedAt: z.number().optional(), completeAt: z.number().optional(), autoRepeat: z.boolean(), pausedAt: z.number().optional(), blockedReason: z.string().optional() }),
    crafting: z.object({ status: statusSchema, recipeId: z.string().optional(), startedAt: z.number().optional(), completeAt: z.number().optional(), autoRepeat: z.boolean(), pausedAt: z.number().optional(), blockedReason: z.string().optional() })
  }),
  unlocks: z.object({ zones: z.array(z.string()), recipes: z.array(z.string()), automations: z.array(z.enum(['autoLumber', 'autoFishing', 'autoMining', 'autoWorkshop'])) }),
  eventLog: z.array(z.object({ id: z.string(), at: z.number(), message: z.string(), tone: z.enum(['info', 'success', 'warning', 'danger']) })).max(80)
});

export type SaveData = z.infer<typeof saveSchema>;

