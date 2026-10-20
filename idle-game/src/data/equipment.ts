import type { EquipmentTemplate } from '../game-engine/types';

export const equipmentTemplates: EquipmentTemplate[] = [
  { id: 'woodenSword', name: '边境短剑', slot: 'weapon', tier: 1, description: '村铁匠用旧铁片打磨出的短剑。', statRanges: { attack: { min: 4, max: 7 } }, durability: 20, brokenStats: { attack: 1 }, recipeId: 'craftWoodenSword' },
  { id: 'linenArmor', name: '缝补皮甲', slot: 'armor', tier: 1, description: '轻便、耐脏，能挡住最初几次撕咬。', statRanges: { defense: { min: 2, max: 4 }, health: { min: 5, max: 9 } }, durability: 20, brokenStats: { defense: 1, health: 2 }, recipeId: 'craftLinenArmor' },
  { id: 'riverCharm', name: '河石护符', slot: 'accessory', tier: 1, description: '河床圆石串成的护符，握住它会安心一些。', statRanges: { health: { min: 4, max: 8 }, speed: { min: 2, max: 5 } }, durability: 20, brokenStats: { health: 2, speed: 1 }, recipeId: 'craftRiverCharm' },
  { id: 'fangBlade', name: '獠牙刃', slot: 'weapon', tier: 2, description: '把野兽牙嵌入剑脊，挥动时带着尖锐的破风声。', statRanges: { attack: { min: 9, max: 14 }, speed: { min: 2, max: 5 } }, durability: 26, brokenStats: { attack: 3, speed: 1 }, recipeId: 'craftFangBlade' },
  { id: 'hunterVest', name: '猎人背心', slot: 'armor', tier: 2, description: '用厚皮和粗布缝成，适合在林间长途跋涉。', statRanges: { defense: { min: 6, max: 10 }, health: { min: 12, max: 20 } }, durability: 26, brokenStats: { defense: 2, health: 5 }, recipeId: 'craftHunterVest' },
  { id: 'amberLoop', name: '琥珀指环', slot: 'accessory', tier: 2, description: '浑浊的琥珀中封着一片小叶子。', statRanges: { attack: { min: 3, max: 6 }, speed: { min: 5, max: 9 } }, durability: 26, brokenStats: { attack: 1, speed: 2 }, recipeId: 'craftAmberLoop' },
  { id: 'ironMace', name: '锻铁重锤', slot: 'weapon', tier: 3, description: '沉重的锻铁锤，专门用来敲碎傀儡的关节。', statRanges: { attack: { min: 18, max: 26 }, defense: { min: 2, max: 5 } }, durability: 32, brokenStats: { attack: 6, defense: 1 }, recipeId: 'craftIronMace' },
  { id: 'scaleMail', name: '晶鳞护甲', slot: 'armor', tier: 3, description: '晶脊蜥鳞片叠成的甲片，反射着冷白光。', statRanges: { defense: { min: 13, max: 19 }, health: { min: 25, max: 38 } }, durability: 32, brokenStats: { defense: 4, health: 9 }, recipeId: 'craftScaleMail' },
  { id: 'minerSigil', name: '矿灯徽记', slot: 'accessory', tier: 3, description: '矿工协会的旧徽记，能让人更快抓住战机。', statRanges: { speed: { min: 10, max: 16 }, health: { min: 12, max: 20 } }, durability: 32, brokenStats: { speed: 3, health: 4 }, recipeId: 'craftMinerSigil' },
  { id: 'ashSaber', name: '灰烬军刀', slot: 'weapon', tier: 4, description: '旧王关的制式军刀，刀身仍有暗红余温。', statRanges: { attack: { min: 32, max: 44 }, speed: { min: 7, max: 12 } }, durability: 40, brokenStats: { attack: 10, speed: 2 }, recipeId: 'craftAshSaber' },
  { id: 'gateBulwark', name: '王关壁垒', slot: 'armor', tier: 4, description: '厚重到几乎无法奔跑，却能挡住守卫的重击。', statRanges: { defense: { min: 24, max: 34 }, health: { min: 45, max: 65 } }, durability: 40, brokenStats: { defense: 8, health: 15 }, recipeId: 'craftGateBulwark' },
  { id: 'starShard', name: '星痕碎片', slot: 'accessory', tier: 4, description: '旧王关中留下的晶体，贴近皮肤时微微发热。', statRanges: { attack: { min: 10, max: 17 }, speed: { min: 15, max: 23 }, health: { min: 18, max: 28 } }, durability: 40, brokenStats: { attack: 3, speed: 5, health: 6 }, recipeId: 'craftStarShard' }
];

