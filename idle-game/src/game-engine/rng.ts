import type { RandomSource } from './types';

export const systemRandom: RandomSource = {
  int(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;
  }
};

export const fixedRandom = (value: number): RandomSource => ({
  int(min, max) {
    return Math.max(min, Math.min(max, value));
  }
});
