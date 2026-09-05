/** Load shared :8501 grid_verification_client.js — single implementation, no copy. */

declare global {
  interface Window {
    GridKeyholder?: {
      hasKey: () => boolean;
      signChallenge: (base: string) => Promise<{ keyholder: Record<string, unknown> }>;
    };
    GridVerificationClient?: {
      SCHEMA: string;
      BROWSER_SIGNER: string;
      isAsterChatBody: (body: { model?: string }) => boolean;
      attachToChatBody: (
        chatBody: Record<string, unknown>,
        gwOrBase: string,
      ) => Promise<Record<string, unknown>>;
    };
  }
}

let gatewayBaseCache: string | null = null;

export function resolveGridGatewayBase(): string {
  if (gatewayBaseCache) return gatewayBaseCache;
  const host = location.hostname;
  if (host.endsWith('.ts.net')) {
    gatewayBaseCache = location.origin;
    return gatewayBaseCache;
  }
  const h = host === 'localhost' ? '127.0.0.1' : host;
  gatewayBaseCache = `http://${h}:8501`;
  return gatewayBaseCache;
}

async function loadScript(src: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`script load failed: ${src}`));
    document.head.appendChild(s);
  });
}

export async function ensureGridVerificationScripts(): Promise<void> {
  const base = resolveGridGatewayBase();
  if (!window.GridKeyholder) {
    await loadScript(`${base}/app/grid_keyholder.js`);
  }
  if (!window.GridVerificationClient) {
    await loadScript(`${base}/app/grid_verification_client.js`);
  }
}

export async function attachBrowserVerification(
  chatBody: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  await ensureGridVerificationScripts();
  const gvc = window.GridVerificationClient;
  if (!gvc) throw new Error('GridVerificationClient unavailable');
  if (!gvc.isAsterChatBody(chatBody)) return chatBody;
  return gvc.attachToChatBody(chatBody, resolveGridGatewayBase());
}
