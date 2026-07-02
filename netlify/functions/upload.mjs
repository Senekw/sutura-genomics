// POST /api/upload  (redirected from netlify.toml -> /.netlify/functions/upload)
//
// Receives an uploaded .h5ad from the demo dashboard and confirms reception.
// This is a lightweight receiver: it validates that the payload really is an
// HDF5 file (.h5ad is HDF5 under the hood) and writes it to the function's
// ephemeral /tmp, then echoes back the filename + spot count.
//
// Why not parse spot count here: Netlify's synchronous functions cap the
// request body at ~6 MB, while real DLPFC .h5ad files are ~100 MB. So the
// browser parses the true spot count locally (h5wasm) and sends it in a
// header; for large files the client uploads only the file header slice (which
// still carries the HDF5 signature) so validation + reception stay real.

import { writeFile } from "node:fs/promises";
import { join } from "node:path";

// HDF5 files start with the signature \x89 H D F \r \n \x1a \n
const HDF5_MAGIC = Buffer.from([0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a]);

const json = (statusCode, body) => ({
  statusCode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return json(405, { error: "Method not allowed" });
  }

  const filename = (event.headers["x-filename"] || "upload.h5ad").toString();
  const declaredSize = Number(event.headers["x-filesize"] || 0);
  const spots = Number(event.headers["x-spots"] || 0);

  if (!/\.h5ad$/i.test(filename)) {
    return json(400, { error: "Only .h5ad files are accepted." });
  }

  if (!event.body) {
    return json(400, { error: "Empty upload." });
  }

  const bytes = event.isBase64Encoded
    ? Buffer.from(event.body, "base64")
    : Buffer.from(event.body, "binary");

  // Validate the HDF5 signature (the file — or its leading slice — must be HDF5).
  if (bytes.length < 8 || !bytes.subarray(0, 8).equals(HDF5_MAGIC)) {
    return json(415, { error: "That doesn't look like a valid .h5ad (HDF5) file." });
  }

  // Save to the function's ephemeral /tmp (demo reception only — not persisted).
  try {
    await writeFile(join("/tmp", `sutura-${Date.now()}-${filename.replace(/[^\w.-]/g, "_")}`), bytes);
  } catch {
    // /tmp write is best-effort; reception is still considered successful.
  }

  return json(200, {
    ok: true,
    filename,
    spots: Number.isFinite(spots) && spots > 0 ? spots : null,
    receivedBytes: bytes.length,
    fileSize: Number.isFinite(declaredSize) && declaredSize > 0 ? declaredSize : bytes.length,
    truncated: declaredSize > bytes.length,
  });
};
