import type { ZoneConfig } from '../game-engine/types';

export const zones: ZoneConfig[] = [
  {
    id: 'mossyTrail', name: '苔痕小径', description: '边境村外的潮湿小径，史莱姆在石缝中缓慢蠕动。', unlockLevel: 1,
    enemy: { name: '绿苔史莱姆', stats: { attack: 3, defense: 1, health: 24, speed: 0 } }, experience: 8, gold: 2,
    drops: [{ materialId: 'slimeGel', min: 1, max: 2, chance: 1 }, { materialId: 'wood', min: 1, max: 1, chance: 0.35 }]
  },
  {
    id: 'fangWoods', name: '獠牙林', description: '林中留下新鲜抓痕，野兽开始试探营火边缘。', unlockLevel: 3,
    enemy: { name: '獠牙野猪', stats: { attack: 7, defense: 3, health: 55, speed: 12 } }, experience: 17, gold: 4,
    drops: [{ materialId: 'fang', min: 1, max: 2, chance: 1 }, { materialId: 'wood', min: 1, max: 2, chance: 0.55 }]
  },
  {
    id: 'gravelWaste', name: '沙砾荒原', description: '风沙掩埋旧路，盗匪傀儡在废墟间巡逻。', unlockLevel: 5,
    enemy: { name: '锈甲傀儡', stats: { attack: 13, defense: 7, health: 118, speed: -5 } }, experience: 34, gold: 8,
    drops: [{ materialId: 'cloth', min: 1, max: 2, chance: 1 }, { materialId: 'ore', min: 1, max: 2, chance: 0.65 }]
  },
  {
    id: 'echoMine', name: '回声矿洞', description: '矿洞深处传来整齐的回声，微光晶在黑暗中回应火把。', unlockLevel: 7,
    enemy: { name: '晶脊蜥', stats: { attack: 21, defense: 11, health: 230, speed: 18 } }, experience: 64, gold: 14,
    drops: [{ materialId: 'crystal', min: 1, max: 2, chance: 1 }, { materialId: 'ore', min: 2, max: 3, chance: 0.8 }]
  },
  {
    id: 'oldGate', name: '旧王关', description: '王关大门锈迹斑斑，门后的守卫仍在等待挑战者。', unlockLevel: 9,
    enemy: { name: '灰烬守卫', stats: { attack: 34, defense: 18, health: 480, speed: 8 } }, experience: 125, gold: 28,
    drops: [{ materialId: 'crystal', min: 2, max: 4, chance: 1 }, { materialId: 'fang', min: 2, max: 3, chance: 0.75 }]
  }
];

