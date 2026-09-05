/**
 * 8790 日记 API 鉴权 — 注入 PIN unlock bearer，不持有 gateway 签名能力。
 * 8501 grid_store 写入仍由 8790 后端代签（X-Grid-Token）。
 */
import { getDiaryToken } from '../settings/panel';

export type DiaryAuthFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export const diaryAuthFetch: DiaryAuthFetch = async (input, init = {}) => {
  const headers = new Headers(init.headers ?? {});
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  const token = getDiaryToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
};
