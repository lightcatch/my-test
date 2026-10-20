import type { GameState } from '../game-engine/types';
import { saveSchema, type SaveData } from './schema';

export const SAVE_KEY = 'idle-game:save:v1';
export const BACKUP_KEY = 'idle-game:save:backup';

export interface SaveRepository {
  load(): SaveData | null;
  save(data: GameState): void;
  exportJson(data: GameState): string;
  importJson(raw: string): SaveData;
  clear(): void;
}

export const localRepository: SaveRepository = {
  load() {
    const raw = localStorage.getItem(SAVE_KEY) ?? localStorage.getItem(BACKUP_KEY);
    if (!raw) return null;
    try {
      return saveSchema.parse(JSON.parse(raw));
    } catch {
      return null;
    }
  },
  save(data) {
    const parsed = saveSchema.parse(data);
    const previous = localStorage.getItem(SAVE_KEY);
    if (previous) localStorage.setItem(BACKUP_KEY, previous);
    localStorage.setItem(SAVE_KEY, JSON.stringify(parsed));
  },
  exportJson(data) {
    return JSON.stringify(saveSchema.parse(data), null, 2);
  },
  importJson(raw) {
    return saveSchema.parse(JSON.parse(raw));
  },
  clear() {
    localStorage.removeItem(SAVE_KEY);
    localStorage.removeItem(BACKUP_KEY);
  }
};
