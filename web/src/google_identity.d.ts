export {};

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: {
          initialize: (opts: { client_id: string; callback: (resp: { credential?: string }) => void }) => void;
          renderButton: (el: HTMLElement, opts?: Record<string, any>) => void;
          prompt: () => void;
        };
      };
    };
  }
}

