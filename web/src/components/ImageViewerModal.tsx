import { useEffect, useMemo, useState } from "react";

type ImageViewerModalProps = {
  open: boolean;
  imageUrls: string[];
  initialIndex?: number;
  onClose: () => void;
};

function clampIndex(i: number, n: number): number {
  if (n <= 0) return 0;
  if (i < 0) return 0;
  if (i >= n) return n - 1;
  return i;
}

export default function ImageViewerModal({ open, imageUrls, initialIndex = 0, onClose }: ImageViewerModalProps) {
  const urls = useMemo(() => imageUrls.filter(Boolean), [imageUrls]);
  const [idx, setIdx] = useState<number>(clampIndex(initialIndex, urls.length));
  const [touchStartX, setTouchStartX] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!open) return;
    setIdx(clampIndex(initialIndex, urls.length));
    setLoaded(false);
  }, [open, initialIndex, urls.length]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (urls.length > 1 && e.key === "ArrowLeft") setIdx((v) => (v - 1 + urls.length) % urls.length);
      if (urls.length > 1 && e.key === "ArrowRight") setIdx((v) => (v + 1) % urls.length);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, urls.length]);

  useEffect(() => {
    setLoaded(false);
  }, [idx]);

  if (!open || !urls.length) return null;

  return (
    <div className="img-viewer-overlay" onClick={onClose}>
      <div className="img-viewer-shell" onClick={(e) => e.stopPropagation()}>
        <button className="img-viewer-close" onClick={onClose}>
          Close
        </button>

        {urls.length > 1 ? (
          <>
            <button className="img-viewer-nav img-viewer-prev" onClick={() => setIdx((v) => (v - 1 + urls.length) % urls.length)}>
              ◀
            </button>
            <button className="img-viewer-nav img-viewer-next" onClick={() => setIdx((v) => (v + 1) % urls.length)}>
              ▶
            </button>
          </>
        ) : null}

        <div
          className="img-viewer-stage"
          onTouchStart={(e) => setTouchStartX(e.touches[0]?.clientX ?? null)}
          onTouchEnd={(e) => {
            if (urls.length <= 1 || touchStartX == null) return;
            const x2 = e.changedTouches[0]?.clientX ?? touchStartX;
            const diff = x2 - touchStartX;
            if (Math.abs(diff) < 40) return;
            if (diff > 0) setIdx((v) => (v - 1 + urls.length) % urls.length);
            else setIdx((v) => (v + 1) % urls.length);
          }}
        >
          {!loaded ? <div className="tiny-loader img-viewer-loader" aria-hidden="true" /> : null}
          <img
            src={urls[idx]}
            alt={`Image ${idx + 1}`}
            className="img-viewer-image"
            onLoad={() => setLoaded(true)}
            onError={() => setLoaded(true)}
          />
        </div>

        <div className="img-viewer-index">
          {idx + 1} / {urls.length}
        </div>
      </div>
    </div>
  );
}

