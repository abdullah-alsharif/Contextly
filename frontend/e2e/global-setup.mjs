// Regenerates the smoke fixture before the run (task T033).
import { makeSamplePdf } from "./make-fixture.mjs";

export default function globalSetup() {
  makeSamplePdf();
}