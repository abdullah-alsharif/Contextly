// Generates fixtures/sample.pdf — a tiny, valid one-page PDF with extractable
// text (xref offsets computed at runtime, so it parses with pypdf). The chunk
// text echoes the smoke question so retrieval hits are guaranteed (the fake
// provider's top-K search has no score threshold, docs/rag.md §3).
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "fixtures",
  "sample.pdf",
);

const BODY_TEXT = "The refund period is 30 days from purchase.";

export function makeSamplePdf(outPath = OUT_PATH) {
  const content = `BT /F1 12 Tf 72 720 Td (${BODY_TEXT}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];

  let pdf = "%PDF-1.4\n";
  const offsets = [];
  for (let i = 0; i < objects.length; i++) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${i + 1} 0 obj\n${objects[i]}\nendobj\n`;
  }
  const xrefStart = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (const offset of offsets) {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF\n`;

  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, pdf);
  return outPath;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  makeSamplePdf();
  console.log(`wrote ${OUT_PATH}`);
}