// Browser-side helpers for the demo's .h5ad upload:
//   1. parseSpotCount — reads the real spot (n_obs) count out of the file with
//      h5wasm, entirely client-side (works for any file size).
//   2. uploadH5ad — POSTs the file to /api/upload with a real progress bar.
//      Netlify's sync functions cap the body at ~6 MB; real DLPFC files are
//      ~100 MB, so for large files we upload only the HDF5 header slice (enough
//      for the backend to validate the signature) and pass size/spots as
//      headers. The backend reports back what it received.

// Stay comfortably under Netlify's ~6 MB synchronous-function body limit.
const UPLOAD_LIMIT = 5 * 1024 * 1024;
const HEADER_SLICE = 64 * 1024; // enough to carry the HDF5 superblock/signature

export type UploadResult = {
  ok: boolean;
  filename: string;
  spots: number | null;
  fileSize: number;
  truncated: boolean;
  backendConfirmed: boolean;
};

// Reads n_obs from an AnnData .h5ad. Returns null if it can't be determined.
export async function parseSpotCount(file: File): Promise<number | null> {
  try {
    const imported = await import("h5wasm");
    // h5wasm exposes its API on the default export in some builds, top-level in
    // others — normalize both.
    const h5wasm = (
      (imported as { default?: unknown }).default ?? imported
    ) as typeof import("h5wasm");
    const mod = await h5wasm.ready;
    const FS = (h5wasm as unknown as { FS?: typeof mod.FS }).FS ?? mod.FS;

    const buf = new Uint8Array(await file.arrayBuffer());
    const name = "upload.h5ad";
    FS.writeFile(name, buf);

    const f = new h5wasm.File(name, "r");
    try {
      // Preferred: length of obs/_index. Fall back to the X matrix shape.
      const idx = f.get("obs/_index");
      if (idx && "shape" in idx && Array.isArray(idx.shape) && idx.shape[0]) {
        return idx.shape[0];
      }
      const x = f.get("X");
      if (x) {
        // Dense matrix: shape[0] = n_obs.
        if ("shape" in x && Array.isArray(x.shape) && x.shape[0]) return x.shape[0];
        // Sparse CSR group: indptr length = n_obs + 1.
        if ("get" in x && typeof x.get === "function") {
          const indptr = (x as { get: (k: string) => unknown }).get("indptr");
          if (indptr && typeof indptr === "object" && "shape" in indptr) {
            const s = (indptr as { shape: number[] }).shape;
            if (Array.isArray(s) && s[0] > 1) return s[0] - 1;
          }
        }
      }
      return null;
    } finally {
      f.close();
      try {
        FS.unlink(name);
      } catch {
        /* ignore */
      }
    }
  } catch {
    return null;
  }
}

export function uploadH5ad(
  file: File,
  spots: number | null,
  onProgress: (fraction: number) => void
): Promise<UploadResult> {
  return new Promise((resolve) => {
    const truncated = file.size > UPLOAD_LIMIT;
    const body: Blob = truncated ? file.slice(0, HEADER_SLICE) : file;

    const fallback: UploadResult = {
      ok: false,
      filename: file.name,
      spots,
      fileSize: file.size,
      truncated,
      backendConfirmed: false,
    };

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("X-Filename", file.name);
    xhr.setRequestHeader("X-Filesize", String(file.size));
    if (spots != null) xhr.setRequestHeader("X-Spots", String(spots));

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.min(1, e.loaded / e.total));
    };
    xhr.onload = () => {
      onProgress(1);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          resolve({
            ok: true,
            filename: data.filename ?? file.name,
            spots: data.spots ?? spots,
            fileSize: data.fileSize ?? file.size,
            truncated: Boolean(data.truncated) || truncated,
            backendConfirmed: true,
          });
          return;
        } catch {
          /* fall through */
        }
      }
      // Backend unavailable (e.g. local dev without Netlify) or error: fall
      // back to the locally parsed result so the demo still proceeds.
      resolve(fallback);
    };
    xhr.onerror = () => resolve(fallback);
    xhr.send(body);
  });
}
