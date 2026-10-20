import { create } from 'zustand';
import { createInitialState } from '../game-engine/initialState';
import { applyCommand } from '../game-engine/reducer';
import { advance } from '../game-engine/simulation';
import { systemRandom } from '../game-engine/rng';
import type { GameCommand, GameState } from '../game-engine/types';
import { migrateSave } from '../persistence/migrations';
import { localRepository } from '../persistence/repository';

interface GameStore {
  game: GameState;
  uiNow: number;
  hydrated: boolean;
  error?: string;
  dispatch: (command: GameCommand) => void;
  tick: (now: number, offline?: boolean) => void;
  load: () => void;
  save: () => void;
  reset: () => void;
  exportSave: () => string;
  importSave: (raw: string) => void;
  clearError: () => void;
}

let saveTimer: number | undefined;

function scheduleSave(state: GameState): void {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => localRepository.save(state), 150);
}

export const useGameStore = create<GameStore>((set, get) => ({
  game: createInitialState(),
  uiNow: Date.now(),
  hydrated: false,
  dispatch(command) {
    const now = Date.now();
    const result = applyCommand(get().game, command, now, systemRandom);
    set({ game: result.state, uiNow: now, error: result.error });
    if (!result.error) scheduleSave(result.state);
  },
  tick(now, offline = false) {
    const current = get().game;
    const result = advance(current, now, systemRandom, { offline });
    set({ game: result.state, uiNow: now });
    if (result.state.savedAt !== current.savedAt) scheduleSave(result.state);
  },
  load() {
    const now = Date.now();
    const stored = localRepository.load();
    if (!stored) {
      const initial = createInitialState(now);
      set({ game: initial, uiNow: now, hydrated: true });
      scheduleSave(initial);
      return;
    }
    try {
      const migrated = migrateSave(stored, now);
      const resumed = advance(migrated, now, systemRandom, { offline: true }).state;
      set({ game: resumed, uiNow: now, hydrated: true });
      scheduleSave(resumed);
    } catch {
      const initial = createInitialState(now);
      set({ game: initial, uiNow: now, hydrated: true, error: '存档无法读取，已创建新存档。' });
      scheduleSave(initial);
    }
  },
  save() {
    localRepository.save(get().game);
  },
  reset() {
    localRepository.clear();
    const initial = createInitialState(Date.now());
    set({ game: initial, uiNow: Date.now(), error: undefined });
    scheduleSave(initial);
  },
  exportSave() {
    return localRepository.exportJson(get().game);
  },
  importSave(raw) {
    try {
      const imported = migrateSave(localRepository.importJson(raw));
      set({ game: imported, uiNow: Date.now(), error: undefined });
      scheduleSave(imported);
    } catch {
      set({ error: '存档格式无效，未覆盖当前进度。' });
    }
  },
  clearError() {
    set({ error: undefined });
  }
}));
