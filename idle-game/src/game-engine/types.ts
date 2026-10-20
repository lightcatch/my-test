export type StatType = 'attack' | 'defense' | 'health' | 'speed';
export type EquipmentSlot = 'weapon' | 'armor' | 'accessory';
export type MaterialId =
  | 'wood'
  | 'fish'
  | 'ore'
  | 'slimeGel'
  | 'fang'
  | 'cloth'
  | 'crystal';
export type PotionId = 'minorPotion';
export type ActivityStatus = 'idle' | 'running' | 'paused' | 'blocked';
export type ActivityType = 'combat' | 'gathering' | 'crafting';

export interface Stats {
  attack: number;
  defense: number;
  health: number;
  speed: number;
}

export interface StatRange {
  min: number;
  max: number;
}

export interface PlayerState {
  level: number;
  experience: number;
  experienceToNext: number;
  gold: number;
  health: number;
  maxHealth: number;
  baseStats: Stats;
  potions: Record<PotionId, number>;
}

export interface EquipmentTemplate {
  id: string;
  name: string;
  slot: EquipmentSlot;
  tier: number;
  description: string;
  statRanges: Partial<Record<StatType, StatRange>>;
  durability: number;
  brokenStats: Partial<Record<StatType, number>>;
  recipeId: string;
}

export interface EquipmentItem {
  instanceId: string;
  templateId: string;
  rolledStats: Partial<Record<StatType, number>>;
  statRangesSnapshot: Partial<Record<StatType, StatRange>>;
  currentDurability: number;
  maxDurability: number;
  createdAt: number;
}

export interface DropEntry {
  materialId: MaterialId;
  min: number;
  max: number;
  chance?: number;
}

export interface CombatantConfig {
  name: string;
  stats: Stats;
}

export interface ZoneConfig {
  id: string;
  name: string;
  description: string;
  unlockLevel: number;
  enemy: CombatantConfig;
  experience: number;
  gold: number;
  drops: DropEntry[];
}

export interface RecipeCost {
  materialId: MaterialId;
  amount: number;
}

export type RecipeOutput =
  | { kind: 'equipment'; templateId: string }
  | { kind: 'potion'; potionId: PotionId; amount: number }
  | { kind: 'automation'; automationId: AutomationId };

export interface RecipeConfig {
  id: string;
  name: string;
  description: string;
  category: 'equipment' | 'potion' | 'facility';
  costs: RecipeCost[];
  durationMs: number;
  output: RecipeOutput;
  unlockLevel: number;
}

export type AutomationId = 'autoLumber' | 'autoFishing' | 'autoMining' | 'autoWorkshop';
export type GatheringTargetId = 'lumber' | 'fishing' | 'mining';

export interface CombatActivity {
  status: ActivityStatus;
  zoneId?: string;
  battleId?: string;
  enemyHp: number;
  enemyMaxHp: number;
  battleStartedAt?: number;
  heroHealthAtStart: number;
  nextHeroAttackAt?: number;
  nextEnemyAttackAt?: number;
  heroHitsDone: number;
  enemyHitsDone: number;
  pausedAt?: number;
  blockedReason?: string;
}

export interface GatheringActivity {
  status: ActivityStatus;
  targetId?: GatheringTargetId;
  startedAt?: number;
  completeAt?: number;
  autoRepeat: boolean;
  pausedAt?: number;
  blockedReason?: string;
}

export interface CraftingActivity {
  status: ActivityStatus;
  recipeId?: string;
  startedAt?: number;
  completeAt?: number;
  autoRepeat: boolean;
  pausedAt?: number;
  blockedReason?: string;
}

export interface ActivityState {
  combat: CombatActivity;
  gathering: GatheringActivity;
  crafting: CraftingActivity;
}

export interface UnlockState {
  zones: string[];
  recipes: string[];
  automations: AutomationId[];
}

export interface GameEvent {
  id: string;
  at: number;
  message: string;
  tone: 'info' | 'success' | 'warning' | 'danger';
}

export interface GameState {
  schemaVersion: number;
  savedAt: number;
  lastActiveAt: number;
  player: PlayerState;
  materials: Record<MaterialId, number>;
  equipment: EquipmentItem[];
  equipped: Partial<Record<EquipmentSlot, string>>;
  activities: ActivityState;
  unlocks: UnlockState;
  eventLog: GameEvent[];
}

export type GameCommand =
  | { type: 'startCombat'; zoneId: string }
  | { type: 'pauseCombat' }
  | { type: 'retreat' }
  | { type: 'startGathering'; targetId: GatheringTargetId; automated?: boolean }
  | { type: 'pauseGathering' }
  | { type: 'startCrafting'; recipeId: string; automated?: boolean }
  | { type: 'pauseCrafting' }
  | { type: 'equipItem'; instanceId: string }
  | { type: 'unequipItem'; slot: EquipmentSlot }
  | { type: 'usePotion'; potionId: PotionId }
  | { type: 'repairItem'; instanceId: string }
  | { type: 'repairAll' }
  | { type: 'dismantleItem'; instanceId: string }
  | { type: 'enableAutomation'; automationId: AutomationId };

export interface RandomSource {
  int(min: number, max: number): number;
}

export interface SimulationResult {
  state: GameState;
  messages: GameEvent[];
}

export interface TransitionResult extends SimulationResult {
  error?: string;
}
