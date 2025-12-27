#!/usr/bin/env node
/**
 * Generate backend JSON schemas from the frontend container.
 *
 * In containerized runs (like Playwright), `make` may be unavailable. If schemas
 * already exist, we skip regeneration to avoid failing `npm run dev`.
 */

import { execSync } from 'child_process';
import { existsSync, readdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const DEFAULT_SCHEMA_DIRS = [
  join(__dirname, '..', '..', 'schemas'), // monorepo root
  join(__dirname, '..', 'schemas'), // frontend container root
].filter(Boolean);

function pickSchemaDir() {
  const candidates = [
    process.env.SCHEMAS_DIR,
    ...DEFAULT_SCHEMA_DIRS,
  ].filter(Boolean);

  for (const dir of candidates) {
    if (!existsSync(dir)) {
      continue;
    }
    const files = readdirSync(dir).filter((name) => name.endsWith('.json'));
    if (files.length > 0) {
      return dir;
    }
  }

  return null;
}

const SCHEMAS_DIR = pickSchemaDir();
const ROOT_DIR = SCHEMAS_DIR ? dirname(SCHEMAS_DIR) : join(__dirname, '..', '..');

function hasMake() {
  try {
    execSync('command -v make', { stdio: 'ignore', shell: true });
    return true;
  } catch {
    return false;
  }
}

function schemasExist() {
  return Boolean(SCHEMAS_DIR);
}

function shouldSkip() {
  const flag = process.env.SKIP_SCHEMA_GEN;
  return flag === '1' || flag === 'true';
}

function run() {
  const force = process.env.FORCE_SCHEMA_GEN;
  const shouldForce = force === '1' || force === 'true';

  if (shouldSkip()) {
    console.log('Skipping schema generation (SKIP_SCHEMA_GEN is set).');
    return;
  }

  const makeAvailable = hasMake();
  const existingSchemas = schemasExist();

  if (existingSchemas && !shouldForce) {
    console.log(`Skipping schema generation (schemas present at ${SCHEMAS_DIR}).`);
    return;
  }

  if (!makeAvailable) {
    console.error('✗ "make" is not available to generate schemas.');
    console.error('  Run "make generate-schemas" from the project root in the api container.');
    process.exit(1);
  }

  execSync('make generate-schemas', { cwd: ROOT_DIR, stdio: 'inherit' });
}

run();
