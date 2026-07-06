export type FieldState = 'idle' | 'thinking' | 'working' | 'output' | 'error';
export const W_OF: Record<FieldState, [number, number, number, number]> = {
  idle: [1,0,0,0], thinking: [0,1,0,0], working: [0,0,1,0], output: [0,0,0,1], error: [1,0,0,0],
};
export interface StateEvent {
  state: FieldState; tokens?: number; coherence?: number;
  links?: { gateway?: boolean; garden?: boolean };
}
