import { CSSProperties, useEffect, useState } from "react";

type ImageWithTinyLoaderProps = {
  src: string;
  alt: string;
  imgStyle?: CSSProperties;
  wrapperStyle?: CSSProperties;
  onClick?: () => void;
  loading?: "lazy" | "eager";
};

export default function ImageWithTinyLoader({ src, alt, imgStyle, wrapperStyle, onClick, loading = "lazy" }: ImageWithTinyLoaderProps) {
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
  }, [src]);

  return (
    <div className="tiny-image-wrap" style={wrapperStyle}>
      {!loaded ? <div className="tiny-loader" aria-hidden="true" /> : null}
      <img
        src={src}
        alt={alt}
        loading={loading}
        className={`tiny-image ${loaded ? "tiny-image-loaded" : "tiny-image-loading"}`}
        style={imgStyle}
        onLoad={() => setLoaded(true)}
        onError={() => setLoaded(true)}
        onClick={onClick}
      />
    </div>
  );
}

