import { useEffect, useState } from "react";

import { tokens } from "@/lib/api";

import { Spinner } from "./Spinner";

interface AuthImageProps {
  /** API path (without /api prefix), e.g. `/pages/<id>/image?variant=processed`. */
  path: string;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
  onError?: (message: string) => void;
  /** Called once the decoded image is laid out and measurable. */
  onLoad?: () => void;
}

/**
 * Page scans live behind an authorised endpoint, so an <img src> cannot be used
 * directly. This fetches the bytes with the bearer token and serves them from a
 * short-lived object URL that is revoked on unmount.
 */
export function AuthImage({ path, alt, className = "", style, onError, onLoad }: AuthImageProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setUrl(null);
    setFailed(null);

    const controller = new AbortController();
    const access = tokens.access();

    fetch(`/api${path}`, {
      headers: access ? { Authorization: `Bearer ${access}` } : undefined,
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Image unavailable (${res.status})`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        const message = err instanceof Error ? err.message : "Image unavailable";
        setFailed(message);
        onError?.(message);
      });

    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  if (failed) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-space-xs bg-surface-container-low text-center ${className}`}
      >
        <span className="material-symbols-outlined text-[24px] text-outline">image_not_supported</span>
        <span className=" text-body-sm text-on-surface-variant">{failed}</span>
      </div>
    );
  }

  if (!url) {
    return (
      <div className={`flex items-center justify-center bg-surface-container-low ${className}`}>
        <Spinner />
      </div>
    );
  }

  return <img src={url} alt={alt} className={className} style={style} onLoad={onLoad} />;
}
