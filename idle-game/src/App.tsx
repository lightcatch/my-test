import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import { Backpack, BookOpen, Hammer, Heart, Pause, Play, RotateCcw, Save, ScrollText, Shield, Sparkles, Swords, Trees, Wrench, X } from 'lucide-react';
import { equipmentTemplates } from './data/equipment';
import { gatheringConfigs, materials } from './data/materials';
import { recipes } from './data/recipes';
import { zones } from './data/zones';
import { getEffectiveStats } from './game-engine/utils';
import { getActivityProgress } from './game-engine/simulation';
import type { EquipmentSlot, GameCommand, StatType } from './game-engine/types';
import { useGameStore } from './store/gameStore';
import styles from './styles/App.module.css';

type Tab = 'combat' | 'gathering' | 'crafting' | 'inventory' | 'save';

const tabItems: Array<{ id: Tab; label: string; icon: typeof Swords }> = [
  { id: 'combat', label: '战斗', icon: Swords },
  { id: 'gathering', label: '采集', icon: Trees },
  { id: 'crafting', label: '制作', icon: Hammer },
  { id: 'inventory', label: '背包', icon: Backpack },
  { id: 'save', label: '存档', icon: Save }
];

const statLabels: Record<StatType, string> = { attack: '攻击', defense: '防御', health: '生命', speed: '速度' };
const slotLabels: Record<EquipmentSlot, string> = { weapon: '武器', armor: '护甲', accessory: '饰品' };
const materialMap = Object.fromEntries(materials.map((item) => [item.id, item]));

function formatTime(ms: number): string {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  if (seconds < 60) return `${seconds}秒`;
  return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
}

function ActionButton({ children, onClick, disabled = false, tone = 'default' }: { children: ReactNode; onClick: () => void; disabled?: boolean; tone?: 'default' | 'accent' | 'danger' }) {
  return <button className={`${styles.action} ${styles[tone]}`} onClick={onClick} disabled={disabled}>{children}</button>;
}

function Panel({ title, icon: Icon, children, aside }: { title: string; icon: typeof Swords; children: ReactNode; aside?: ReactNode }) {
  return <section className={styles.panel}><div className={styles.panelHeader}><div className={styles.panelTitle}><Icon size={17} />{title}</div>{aside}</div>{children}</section>;
}

export default function App() {
  const { game, uiNow, hydrated, error, dispatch, tick, load, reset, exportSave, importSave, clearError } = useGameStore();
  const [tab, setTab] = useState<Tab>('combat');
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!hydrated) return;
    const timer = window.setInterval(() => tick(Date.now()), 500);
    const onFocus = () => tick(Date.now(), true);
    const onVisibility = () => { if (document.visibilityState === 'visible') tick(Date.now(), true); };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', onFocus); document.removeEventListener('visibilitychange', onVisibility); };
  }, [hydrated, tick]);

  const effectiveStats = useMemo(() => getEffectiveStats(game), [game]);
  const running = [game.activities.combat.status === 'running' ? '战斗' : '', game.activities.gathering.status === 'running' ? '采集' : '', game.activities.crafting.status === 'running' ? '制作' : ''].filter(Boolean).join(' / ') || '未进行活动';

  const downloadSave = () => {
    const blob = new Blob([exportSave()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = '边境日志存档.json'; anchor.click(); URL.revokeObjectURL(url);
  };

  const onImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) importSave(await file.text());
    event.target.value = '';
  };

  return <div className={styles.app}>
    <header className={styles.topbar}>
      <div><div className={styles.brand}><ScrollText size={20} />边境日志</div><div className={styles.subtitle}>一个勇士的长期记录</div></div>
      <div className={styles.topStats}>
        <div><span>等级</span><strong>{game.player.level}</strong><small>{game.player.experience}/{game.player.experienceToNext} XP</small></div>
        <div className={styles.healthStat}><span>生命</span><strong>{game.player.health}/{game.player.maxHealth}</strong><small><Heart size={12} />脱战缓慢恢复</small></div>
        <div><span>金币</span><strong>{game.player.gold}</strong><small>当前活动：{running}</small></div>
      </div>
    </header>

    {error && <div className={styles.alert}><span>{error}</span><button onClick={clearError}><X size={16} /></button></div>}
    <main className={styles.main}>
      <nav className={styles.tabs}>{tabItems.map(({ id, label, icon: Icon }) => <button key={id} className={tab === id ? styles.tabActive : ''} onClick={() => setTab(id)}><Icon size={16} />{label}</button>)}</nav>
      <div className={styles.layout}>
        <div className={styles.content}>
          {tab === 'combat' && <CombatView game={game} stats={effectiveStats} now={uiNow} dispatch={dispatch} />}
          {tab === 'gathering' && <GatheringView game={game} now={uiNow} dispatch={dispatch} />}
          {tab === 'crafting' && <CraftingView game={game} now={uiNow} dispatch={dispatch} />}
          {tab === 'inventory' && <InventoryView game={game} dispatch={dispatch} />}
          {tab === 'save' && <SaveView onExport={downloadSave} onImport={() => fileRef.current?.click()} onReset={reset} />}
        </div>
        <aside className={styles.sidebar}>
          <Panel title="当前属性" icon={Sparkles}>
            <div className={styles.statGrid}>{(Object.keys(statLabels) as StatType[]).map((key) => <div key={key}><span>{statLabels[key]}</span><strong>{effectiveStats[key]}</strong></div>)}</div>
          </Panel>
          <Panel title="材料储备" icon={Trees}>
            <div className={styles.materialList}>{materials.map((item) => <div key={item.id}><span><i style={{ background: item.color }} />{item.name}</span><strong>{game.materials[item.id] ?? 0}</strong></div>)}</div>
          </Panel>
          <Panel title="冒险日志" icon={BookOpen}>
            <div className={styles.logList}>{game.eventLog.slice(0, 8).map((event) => <div key={event.id} className={styles[`log_${event.tone}`]}><time>{new Date(event.at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time><span>{event.message}</span></div>)}</div>
          </Panel>
        </aside>
      </div>
    </main>
    <input ref={fileRef} type="file" accept="application/json" hidden onChange={onImport} />
  </div>;
}

function CombatView({ game, stats, now, dispatch }: { game: ReturnType<typeof useGameStore.getState>['game']; stats: ReturnType<typeof getEffectiveStats>; now: number; dispatch: (command: GameCommand) => void }) {
  const activity = game.activities.combat;
  const currentZone = zones.find((zone) => zone.id === activity.zoneId);
  return <>
    <div className={styles.heroBlock}><div><p className={styles.eyebrow}>战斗线</p><h1>边境巡猎</h1><p>选择一处区域，让勇士自动迎战相同的敌人。每场战斗都会消耗装备耐久。</p></div><div className={styles.heroIcon}><Swords size={34} /></div></div>
    <Panel title="战斗区域" icon={Swords} aside={activity.status !== 'idle' && <span className={`${styles.status} ${styles[`status_${activity.status}`]}`}>{activity.status === 'running' ? '进行中' : activity.status === 'blocked' ? '已阻断' : '已暂停'}</span>}>
      <div className={styles.zoneList}>{zones.map((zone) => {
        const unlocked = game.unlocks.zones.includes(zone.id);
        const selected = activity.zoneId === zone.id;
        return <div key={zone.id} className={`${styles.zoneRow} ${selected ? styles.selected : ''} ${!unlocked ? styles.locked : ''}`}>
          <div className={styles.zoneInfo}><div className={styles.zoneName}>{unlocked ? zone.name : `??? · 等级 ${zone.unlockLevel} 解锁`}</div><p>{unlocked ? zone.description : '更强的敌人正在等待。'}</p>{unlocked && <div className={styles.enemyMeta}><span>敌人：{zone.enemy.name}</span><span>生命 {zone.enemy.stats.health}</span><span>奖励 {zone.experience} XP</span></div>}</div>
          {unlocked && <ActionButton tone={selected && activity.status === 'running' ? 'danger' : 'accent'} onClick={() => selected && activity.status === 'running' ? dispatch({ type: 'pauseCombat' }) : dispatch({ type: 'startCombat', zoneId: zone.id })}>{selected && activity.status === 'running' ? <><Pause size={15} />暂停</> : <><Play size={15} />出发</>}</ActionButton>}
        </div>;
      })}</div>
      {currentZone && <div className={styles.battleCard}><div className={styles.battleHeader}><div><span className={styles.eyebrow}>当前目标</span><h3>{currentZone.enemy.name}</h3></div><div className={styles.enemyGlyph}>◆</div></div><div className={styles.hpBar}><span style={{ width: `${Math.max(0, activity.enemyHp / activity.enemyMaxHp) * 100}%` }} /></div><div className={styles.hpText}>敌人生命 {Math.max(0, Math.ceil(activity.enemyHp))} / {activity.enemyMaxHp}</div><div className={styles.battleActions}><ActionButton onClick={() => dispatch({ type: 'retreat' })}><RotateCcw size={15} />撤退</ActionButton><ActionButton onClick={() => dispatch({ type: 'usePotion', potionId: 'minorPotion' })} disabled={game.player.potions.minorPotion <= 0 || game.player.health >= game.player.maxHealth}><Heart size={15} />药水 x{game.player.potions.minorPotion}</ActionButton></div>{activity.blockedReason && <p className={styles.blocked}>{activity.blockedReason}</p>}</div>}
    </Panel>
  </>;
}

function GatheringView({ game, now, dispatch }: { game: ReturnType<typeof useGameStore.getState>['game']; now: number; dispatch: (command: GameCommand) => void }) {
  const activity = game.activities.gathering;
  return <><div className={styles.heroBlock}><div><p className={styles.eyebrow}>采集线</p><h1>野外采集</h1><p>点击一次开始一项行动。建成自动化设施后，可以让采集线持续运行。</p></div><div className={styles.heroIcon}><Trees size={34} /></div></div><Panel title="采集点" icon={Trees}><div className={styles.gatherGrid}>{Object.entries(gatheringConfigs).map(([id, config]) => { const targetId = id as keyof typeof gatheringConfigs; const selected = activity.targetId === targetId; const automated = game.unlocks.automations.includes(config.automationId); const progress = selected ? getActivityProgress(game, 'gathering', now) : 0; return <div key={id} className={styles.gatherCard}><div className={styles.cardIcon} style={{ color: materialMap[config.materialId].color }}><Trees size={23} /></div><h3>{config.name}</h3><p>{config.description}</p><div className={styles.cardMeta}>{config.min}-{config.max} {materialMap[config.materialId].name} · {formatTime(config.durationMs)}</div>{selected && activity.status === 'running' && <><div className={styles.progress}><span style={{ width: `${progress * 100}%` }} /></div><small>还需 {formatTime((activity.completeAt ?? now) - now)}</small></>}{selected && activity.status === 'blocked' && <small className={styles.blocked}>{activity.blockedReason}</small>}<ActionButton tone={selected && activity.status === 'running' ? 'danger' : 'accent'} onClick={() => selected && activity.status === 'running' ? dispatch({ type: 'pauseGathering' }) : dispatch({ type: 'startGathering', targetId, automated })}><>{selected && activity.status === 'running' ? <Pause size={15} /> : <Play size={15} />}{selected && activity.status === 'running' ? '暂停' : automated ? '自动开始' : '开始行动'}</></ActionButton>{automated && <span className={styles.autoTag}>已自动化</span>}</div>; })}</div></Panel></>;
}

function CraftingView({ game, now, dispatch }: { game: ReturnType<typeof useGameStore.getState>['game']; now: number; dispatch: (command: GameCommand) => void }) {
  const activity = game.activities.crafting;
  const available = recipes.filter((recipe) => game.unlocks.recipes.includes(recipe.id));
  const grouped = { equipment: available.filter((recipe) => recipe.category === 'equipment'), potion: available.filter((recipe) => recipe.category === 'potion'), facility: available.filter((recipe) => recipe.category === 'facility') };
  return <><div className={styles.heroBlock}><div><p className={styles.eyebrow}>制作线</p><h1>工坊清单</h1><p>每次制作会消耗材料。装备属性在模板范围内独立随机生成。</p></div><div className={styles.heroIcon}><Hammer size={34} /></div></div><Panel title="制作配方" icon={Hammer} aside={game.unlocks.automations.includes('autoWorkshop') && <span className={styles.autoTag}>自动工坊已解锁</span>}>
    {(['equipment', 'potion', 'facility'] as const).map((category) => <div key={category} className={styles.recipeSection}><h3>{category === 'equipment' ? '装备' : category === 'potion' ? '消耗品' : '设施'}</h3><div className={styles.recipeList}>{grouped[category].map((recipe) => { const active = activity.recipeId === recipe.id; const affordable = recipe.costs.every((cost) => (game.materials[cost.materialId] ?? 0) >= cost.amount) && (recipe.output.kind !== 'equipment' || game.equipment.length < 12); const automated = category !== 'facility' && game.unlocks.automations.includes('autoWorkshop'); return <div key={recipe.id} className={`${styles.recipeRow} ${active ? styles.selected : ''}`}><div className={styles.recipeInfo}><strong>{recipe.name}</strong><span>{recipe.description}</span><div className={styles.costs}>{recipe.costs.map((cost) => <em key={cost.materialId} style={{ color: materialMap[cost.materialId].color }}>{materialMap[cost.materialId].shortName} {cost.amount}</em>)}<em>{formatTime(recipe.durationMs)}</em></div></div><ActionButton disabled={!affordable || (category === 'facility' && active)} tone={active && activity.status === 'running' ? 'danger' : 'accent'} onClick={() => active && activity.status === 'running' ? dispatch({ type: 'pauseCrafting' }) : dispatch({ type: 'startCrafting', recipeId: recipe.id, automated })}>{active && activity.status === 'running' ? <><Pause size={15} />暂停</> : <><Hammer size={15} />{automated ? '自动制作' : '制作'}</>}</ActionButton></div>; })}</div></div>)}{activity.blockedReason && <p className={styles.blocked}>{activity.blockedReason}</p>}{activity.status === 'running' && activity.startedAt && activity.completeAt && <div className={styles.craftProgress}><div className={styles.progress}><span style={{ width: `${getActivityProgress(game, 'crafting', now) * 100}%` }} /></div><span>还需 {formatTime(activity.completeAt - now)}</span></div>}</Panel></>;
}

function InventoryView({ game, dispatch }: { game: ReturnType<typeof useGameStore.getState>['game']; dispatch: (command: GameCommand) => void }) {
  const totalSlots = 12;
  return <><div className={styles.heroBlock}><div><p className={styles.eyebrow}>装备线</p><h1>装备与维护</h1><p>装备属性来自制作时的范围随机。耐久每场战斗结束后下降 1 点。</p></div><div className={styles.heroIcon}><Shield size={34} /></div></div><Panel title={`装备栏 ${game.equipment.length}/${totalSlots}`} icon={Backpack} aside={<ActionButton onClick={() => dispatch({ type: 'repairAll' })}><Wrench size={15} />一键修理</ActionButton>}><div className={styles.equipGrid}>{(['weapon', 'armor', 'accessory'] as EquipmentSlot[]).map((slot) => { const itemId = game.equipped[slot]; const item = game.equipment.find((entry) => entry.instanceId === itemId); const template = item && equipmentTemplates.find((entry) => entry.id === item.templateId); return <div className={styles.slotCard} key={slot}><span className={styles.slotLabel}>{slotLabels[slot]}</span>{item && template ? <><strong>{template.name}</strong><div className={styles.itemStats}>{Object.entries(item.rolledStats).map(([key, value]) => <span key={key}>{statLabels[key as StatType]} +{value}</span>)}</div><small className={item.currentDurability <= 0 ? styles.dangerText : ''}>耐久 {item.currentDurability}/{item.maxDurability}</small><div className={styles.rowActions}><ActionButton onClick={() => dispatch({ type: 'unequipItem', slot })}><X size={14} />卸下</ActionButton>{item.currentDurability < item.maxDurability && <ActionButton onClick={() => dispatch({ type: 'repairItem', instanceId: item.instanceId })}><Wrench size={14} />修理</ActionButton>}</div></> : <span className={styles.emptySlot}>未装备</span>}</div>; })}</div><div className={styles.inventoryList}>{game.equipment.map((item) => { const template = equipmentTemplates.find((entry) => entry.id === item.templateId); if (!template) return null; const equipped = Object.values(game.equipped).includes(item.instanceId); return <div className={styles.itemRow} key={item.instanceId}><div><strong>{template.name}</strong><span>{slotLabels[template.slot]} · T{template.tier} · {Object.entries(item.rolledStats).map(([key, value]) => `${statLabels[key as StatType]} +${value}`).join('，')}</span><small className={item.currentDurability <= 0 ? styles.dangerText : ''}>耐久 {item.currentDurability}/{item.maxDurability} · 破损保护 {Object.entries(template.brokenStats).map(([key, value]) => `${statLabels[key as StatType]} +${value}`).join('，')}</small></div><div className={styles.rowActions}>{!equipped && <ActionButton onClick={() => dispatch({ type: 'equipItem', instanceId: item.instanceId })}><Shield size={14} />装备</ActionButton>}{!equipped && <ActionButton onClick={() => dispatch({ type: 'dismantleItem', instanceId: item.instanceId })}><X size={14} />分解</ActionButton>}{item.currentDurability < item.maxDurability && <ActionButton onClick={() => dispatch({ type: 'repairItem', instanceId: item.instanceId })}><Wrench size={14} />修理</ActionButton>}</div></div>; })}</div></Panel></>;
}

function SaveView({ onExport, onImport, onReset }: { onExport: () => void; onImport: () => void; onReset: () => void }) {
  return <><div className={styles.heroBlock}><div><p className={styles.eyebrow}>存档线</p><h1>记录与备份</h1><p>进度自动保存在浏览器中，也可以导出 JSON 保存到本地。</p></div><div className={styles.heroIcon}><Save size={34} /></div></div><Panel title="本地存档" icon={Save}><div className={styles.saveActions}><ActionButton tone="accent" onClick={onExport}><Save size={16} />导出 JSON</ActionButton><ActionButton onClick={onImport}><RotateCcw size={16} />导入 JSON</ActionButton><ActionButton tone="danger" onClick={() => { if (window.confirm('确定要删除当前存档并重新开始吗？')) onReset(); }}><X size={16} />重置存档</ActionButton></div><div className={styles.saveNote}><p>自动保存：已开启</p><p>离线收益上限：8 小时</p><p>当前存档只保存在本设备浏览器中。</p></div></Panel></>;
}
