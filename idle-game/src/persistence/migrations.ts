import { SAVE_VERSION, createInitialState } from '../game-engine/initialState';
import type { GameState } from '../game-engine/types';
import { saveSchema } from './schema';

export function migrateSave(input: unknown, now = Date.now()): GameState {
  const parsed = saveSchema.parse(input);
  if (parsed.schemaVersion === SAVE_VERSION) return parsed as GameState;
  const fresh = createInitialState(now);
  return { ...fresh, ...parsed, schemaVersion: SAVE_VERSION } as GameState;
}

