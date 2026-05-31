#!/usr/bin/env node
/**
 * Generate TypeScript types from JSON Schema files
 *
 * This script uses quicktype to convert JSON Schema files generated from
 * backend Pydantic models into TypeScript type definitions.
 */

import { execSync } from 'child_process';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'fs';
import { tmpdir } from 'os';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const DEFAULT_SCHEMA_DIRS = [
  join(__dirname, '../../schemas'), // monorepo root
  join(__dirname, '../schemas'), // frontend container root
];
const SCHEMAS_DIR = pickSchemaDir();
const COMMITTED_OUTPUT_FILE = join(__dirname, '../src/types/generated/api.ts');
const CHECK_MODE = process.argv.includes('--check');

function pickSchemaDir() {
  const candidates = [
    process.env.SCHEMAS_DIR,
    ...DEFAULT_SCHEMA_DIRS,
  ].filter(Boolean);

  for (const dir of candidates) {
    if (!existsSync(dir)) {
      continue;
    }
    const files = readdirSync(dir)
      .filter(f => f.endsWith('.json') && f !== 'index.json');
    if (files.length > 0) {
      return dir;
    }
  }

  return null;
}

/**
 * Find all JSON Schema files
 */
function findSchemaFiles() {
  if (!SCHEMAS_DIR) {
    console.error('✗ Schemas directory not found.');
    console.error(
      `  Looked in: ${DEFAULT_SCHEMA_DIRS.join(', ')}`
    );
    console.error('  Run "make generate-schemas" from the project root first.');
    process.exit(1);
  }

  const files = readdirSync(SCHEMAS_DIR)
    .filter(f => f.endsWith('.json') && f !== 'index.json')
    .map(f => join(SCHEMAS_DIR, f));

  if (files.length === 0) {
    console.error(`✗ No schema files found in ${SCHEMAS_DIR}`);
    console.error('  Run "make generate-schemas" from the project root first.');
    process.exit(1);
  }

  return files;
}

/**
 * Generate TypeScript types using quicktype
 */
function generateTypes(schemaFiles, outputFile) {
  console.log('🔧 Generating TypeScript types from JSON Schemas...');
  console.log(`   Input: ${SCHEMAS_DIR}`);
  console.log(`   Output: ${outputFile}`);
  console.log(`   Schema files: ${schemaFiles.length}`);

  // Ensure output directory exists
  const outputDir = dirname(outputFile);
  if (!existsSync(outputDir)) {
    mkdirSync(outputDir, { recursive: true });
  }

  try {
    // Build quicktype command
    const schemaArgs = schemaFiles.join(' ');
    const command = `npx quicktype ${schemaArgs} ` +
      `-o ${outputFile} ` +
      `--lang typescript ` +
      `--src-lang schema ` +
      `--just-types ` +
      `--prefer-unions ` +
      `--acronym-style original ` +
      `--no-date-times ` +
      `--prefer-const-values`;

    // Run quicktype
    execSync(command, { stdio: 'inherit' });

    // Add header comment to generated file
    addHeaderComment(outputFile);

    console.log('✓ TypeScript types generated successfully');
    console.log(`  Output: ${outputFile}`);
  } catch (error) {
    console.error('✗ Failed to generate TypeScript types');
    console.error(error.message);
    process.exit(1);
  }
}

/**
 * Add header comment to generated file
 */
function addHeaderComment(outputFile) {
  const generatedCode = readFileSync(outputFile, 'utf-8');

  const header = `/**
 * AUTO-GENERATED FILE - DO NOT EDIT
 *
 * Generated from backend Pydantic models via JSON Schema.
 * To update these types, run: npm run generate:types
 *
 * Generated: ${new Date().toISOString()}
 *
 * Source schemas: ../../../schemas/*.json
 * Generation tool: quicktype (https://quicktype.io/)
 */

/* eslint-disable */
// @ts-nocheck

`;

  writeFileSync(outputFile, header + generatedCode);
}

function normalizeForComparison(content) {
  return content.replace(
    /^ \* Generated: .*$/m,
    ' * Generated: <ignored>'
  );
}

function checkTypes(schemaFiles) {
  if (!existsSync(COMMITTED_OUTPUT_FILE)) {
    console.error(`✗ Missing generated TypeScript API types: ${COMMITTED_OUTPUT_FILE}`);
    process.exit(1);
  }

  const tmpDir = mkdtempSync(join(tmpdir(), 'therapist-generated-types-'));
  const generatedOutput = join(tmpDir, 'api.ts');

  try {
    generateTypes(schemaFiles, generatedOutput);

    const committed = normalizeForComparison(
      readFileSync(COMMITTED_OUTPUT_FILE, 'utf-8')
    );
    const generated = normalizeForComparison(
      readFileSync(generatedOutput, 'utf-8')
    );

    if (committed !== generated) {
      console.error('✗ Generated TypeScript API types are out of date.');
      console.error(
        '  Run `docker compose run --rm -v "$PWD/schemas:/app/schemas" frontend npm run generate:ts`.'
      );
      process.exit(1);
    }

    console.log('✓ Generated TypeScript API types are up to date');
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}

/**
 * Main function
 */
function main() {
  try {
    const schemaFiles = findSchemaFiles();
    if (CHECK_MODE) {
      checkTypes(schemaFiles);
      return;
    }

    generateTypes(schemaFiles, COMMITTED_OUTPUT_FILE);
  } catch (error) {
    console.error('✗ Type generation failed');
    console.error(error.message);
    process.exit(1);
  }
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
