/**
 * Reading the exported measurements at build time.
 *
 * The pages used to fetch these files in the browser. That was a mistake for this project:
 * the built HTML contained no measurements at all, so saving a page, archiving it, or
 * printing it to PDF captured an empty shell — and the whole argument of the site is that its
 * numbers can be checked and cited later. Reading the JSON here, during the static export,
 * bakes the numbers into the HTML instead.
 *
 * This module is server-only. It runs during `next build` and never reaches the browser.
 */

import { readFile } from 'node:fs/promises';
import path from 'node:path';

const DATA_DIR = path.join(process.cwd(), 'public', 'data');

/**
 * Read one exported file, or null if it has not been produced yet.
 *
 * A missing file is not an error. The pipeline produces these one at a time, and a page whose
 * data is absent says so and names the command that writes it, rather than rendering a zero
 * that would read as a measurement.
 */
export async function readExport<T>(name: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(path.join(DATA_DIR, name), 'utf8')) as T;
  } catch {
    return null;
  }
}
