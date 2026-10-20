import type { RecipeConfig } from '../game-engine/types';

const equipment = (id: string, name: string, templateId: string, unlockLevel: number, durationMs: number, costs: RecipeConfig['costs']): RecipeConfig => ({ id, name, description: '制作一件属性范围随机的装备。', category: 'equipment', costs, durationMs, output: { kind: 'equipment', templateId }, unlockLevel });

export const recipes: RecipeConfig[] = [
  equipment('craftWoodenSword', '制作边境短剑', 'woodenSword', 1, 15_000, [{ materialId: 'wood', amount: 6 }, { materialId: 'ore', amount: 2 }]),
  equipment('craftLinenArmor', '制作缝补皮甲', 'linenArmor', 1, 18_000, [{ materialId: 'wood', amount: 4 }, { materialId: 'slimeGel', amount: 3 }]),
  equipment('craftRiverCharm', '制作河石护符', 'riverCharm', 1, 14_000, [{ materialId: 'fish', amount: 3 }, { materialId: 'slimeGel', amount: 2 }]),
  equipment('craftFangBlade', '制作獠牙刃', 'fangBlade', 3, 24_000, [{ materialId: 'fang', amount: 5 }, { materialId: 'ore', amount: 5 }, { materialId: 'wood', amount: 3 }]),
  equipment('craftHunterVest', '制作猎人背心', 'hunterVest', 3, 26_000, [{ materialId: 'fang', amount: 3 }, { materialId: 'cloth', amount: 5 }, { materialId: 'wood', amount: 5 }]),
  equipment('craftAmberLoop', '制作琥珀指环', 'amberLoop', 3, 22_000, [{ materialId: 'fish', amount: 6 }, { materialId: 'slimeGel', amount: 4 }, { materialId: 'ore', amount: 3 }]),
  equipment('craftIronMace', '制作锻铁重锤', 'ironMace', 5, 34_000, [{ materialId: 'ore', amount: 12 }, { materialId: 'fang', amount: 6 }, { materialId: 'wood', amount: 6 }]),
  equipment('craftScaleMail', '制作晶鳞护甲', 'scaleMail', 5, 38_000, [{ materialId: 'ore', amount: 10 }, { materialId: 'crystal', amount: 4 }, { materialId: 'cloth', amount: 8 }]),
  equipment('craftMinerSigil', '制作矿灯徽记', 'minerSigil', 5, 30_000, [{ materialId: 'crystal', amount: 4 }, { materialId: 'fish', amount: 8 }, { materialId: 'ore', amount: 6 }]),
  equipment('craftAshSaber', '制作灰烬军刀', 'ashSaber', 9, 50_000, [{ materialId: 'crystal', amount: 12 }, { materialId: 'ore', amount: 20 }, { materialId: 'fang', amount: 12 }]),
  equipment('craftGateBulwark', '制作王关壁垒', 'gateBulwark', 9, 55_000, [{ materialId: 'crystal', amount: 10 }, { materialId: 'ore', amount: 24 }, { materialId: 'cloth', amount: 16 }]),
  equipment('craftStarShard', '制作星痕碎片', 'starShard', 9, 48_000, [{ materialId: 'crystal', amount: 18 }, { materialId: 'fish', amount: 12 }, { materialId: 'slimeGel', amount: 10 }]),
  { id: 'minorPotion', name: '制作微光药水', description: '恢复 25% 最大生命值，向下取整。', category: 'potion', costs: [{ materialId: 'fish', amount: 2 }, { materialId: 'slimeGel', amount: 2 }], durationMs: 10_000, output: { kind: 'potion', potionId: 'minorPotion', amount: 1 }, unlockLevel: 1 },
  { id: 'autoLumber', name: '制作伐木架', description: '解锁自动伐木。', category: 'facility', costs: [{ materialId: 'wood', amount: 20 }, { materialId: 'ore', amount: 5 }], durationMs: 25_000, output: { kind: 'automation', automationId: 'autoLumber' }, unlockLevel: 2 },
  { id: 'autoFishing', name: '制作抛网架', description: '解锁自动钓鱼。', category: 'facility', costs: [{ materialId: 'wood', amount: 15 }, { materialId: 'fish', amount: 8 }, { materialId: 'ore', amount: 5 }], durationMs: 25_000, output: { kind: 'automation', automationId: 'autoFishing' }, unlockLevel: 3 },
  { id: 'autoMining', name: '制作矿脉滑车', description: '解锁自动采矿。', category: 'facility', costs: [{ materialId: 'wood', amount: 18 }, { materialId: 'ore', amount: 12 }, { materialId: 'slimeGel', amount: 8 }], durationMs: 30_000, output: { kind: 'automation', automationId: 'autoMining' }, unlockLevel: 4 },
  { id: 'autoWorkshop', name: '制作简易工坊', description: '解锁自动循环制作。', category: 'facility', costs: [{ materialId: 'wood', amount: 25 }, { materialId: 'ore', amount: 18 }, { materialId: 'crystal', amount: 3 }], durationMs: 40_000, output: { kind: 'automation', automationId: 'autoWorkshop' }, unlockLevel: 5 }
];

