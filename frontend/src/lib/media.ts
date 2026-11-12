export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

/** Downscale a screenshot so uploads stay small but text stays readable. */
export async function prepareScreenshot(
  file: Blob,
  maxSide = 1600,
): Promise<{ data: string; mime: string; previewUrl: string }> {
  if (!file.type.startsWith("image/")) throw new Error("Please choose an image file (PNG, JPG or WebP).");
  if (file.size > 25 * 1024 * 1024) throw new Error("That image is too large (max 25 MB).");

  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Could not process the image.");
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();

  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Could not encode the image."))), "image/jpeg", 0.88),
  );
  return { data: await blobToBase64(blob), mime: "image/jpeg", previewUrl: URL.createObjectURL(blob) };
}

export function micErrorMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Microphone access was blocked. Click the lock icon in the address bar, allow the microphone, and try again.";
    case "NotFoundError":
      return "No microphone was found. Plug in a microphone or headset and try again.";
    case "NotReadableError":
      return "Your microphone is being used by another app. Close that app and try again.";
    default:
      if (typeof window !== "undefined" && !window.isSecureContext)
        return "The microphone only works on https:// or http://localhost. Open the app from localhost or enable HTTPS.";
      return `Could not start the microphone${err instanceof Error ? `: ${err.message}` : "."}`;
  }
}
