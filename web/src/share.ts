export async function sharePost(opts: { title: string; text: string; url?: string }): Promise<"shared" | "copied" | "unsupported"> {
  const title = String(opts.title || "").trim() || "Share";
  const text = String(opts.text || "").trim();
  const url = String(opts.url || "").trim();

  // Prefer native share sheet on supported mobile browsers.
  const navAny: any = navigator as any;
  if (navAny?.share) {
    try {
      await navAny.share({ title, text, url: url || undefined });
      return "shared";
    } catch {
      // User cancelled or share failed; fall through to clipboard.
    }
  }

  const payload = [text, url].filter(Boolean).join("\n").trim();
  if (!payload) return "unsupported";

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(payload);
      return "copied";
    }
  } catch {
    // fall back to legacy
  }

  try {
    const ta = document.createElement("textarea");
    ta.value = payload;
    ta.setAttribute("readonly", "true");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    return "copied";
  } catch {
    return "unsupported";
  }
}

