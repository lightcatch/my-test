import type { GatheringTargetId, MaterialId } from '../game-engine/types';

export interface MaterialConfig {
  id: MaterialId;
  name: string;
  shortName: string;
  color: string;
  source: string;
}

export const materials: MaterialConfig[] = [
  { id: 'wood', name: '原木', shortName: '木', color: '#b78b5c', source: '伐木' },
  { id: 'fish', name: '河鱼', shortName: '鱼', color: '#69b7c9', source: '钓鱼' },
  { id: 'ore', name: '铁矿', shortName: '矿', color: '#a4abb8', source: '采矿' },
  { id: 'slimeGel', name: '史莱姆胶', shortName: '胶', color: '#79c7a1', source: '苔原边缘' },
  { id: 'fang', name: '野兽牙', shortName: '牙', color: '#e8d0a7', source: '獠牙林' },
  { id: 'cloth', name: '粗布', shortName: '布', color: '#d6a56e', source: '沙砾荒原' },
  { id: 'crystal', name: '微光晶', shortName: '晶', color: '#9ec5ee', source: '回声矿洞' }
];

export const gatheringConfigs: Record<
  GatheringTargetId,
  { name: string; description: string; durationMs: number; materialId: MaterialId; min: number; max: number; automationId: 'autoLumber' | 'autoFishing' | 'autoMining' }
> = {
  lumber: { name: '伐木', description: '从边境林线收集干燥原木。', durationMs: 10_000, materialId: 'wood', min: 2, max: 4, automationId: 'autoLumber' },
  fishing: { name: '钓鱼', description: '在浅滩守候，偶尔能钓到闪鳞鱼。', durationMs: 15_000, materialId: 'fish', min: 1, max: 3, automationId: 'autoFishing' },
  mining: { name: '采矿', description: '敲开露头矿脉，寻找可锻造的铁矿。', durationMs: 20_000, materialId: 'ore', min: 1, max: 2, automationId: 'autoMining' }
};

