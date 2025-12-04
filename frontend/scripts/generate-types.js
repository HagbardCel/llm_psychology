#!/usr/bin/env node
/**
 * Generate TypeScript types from JSON Schema files
 *
 * This script uses quicktype to convert JSON Schema files generated from
 * backend Pydantic models into TypeScript type definitions.
 */

import { execSync } from 'child_process';
import { readdirSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const SCHEMAS_DIR = join(__dirname, '../../schemas');
const OUTPUT_FILE = join(__dirname, '../src/types/generated/api.ts');
const OUTPUT_DIR = dirname(OUTPUT_FILE);

/**
 * Find all JSON Schema files
 */
function findSchemaFiles() {
  if (!existsSync(SCHEMAS_DIR)) {
    console.error(`✗ Schemas directory not found: ${SCHEMAS_DIR}`);
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
function generateTypes(schemaFiles) {
  console.log('🔧 Generating TypeScript types from JSON Schemas...');
  console.log(`   Input: ${SCHEMAS_DIR}`);
  console.log(`   Output: ${OUTPUT_FILE}`);
  console.log(`   Schema files: ${schemaFiles.length}`);

  // Ensure output directory exists
  if (!existsSync(OUTPUT_DIR)) {
    mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  try {
    // Build quicktype command
    const schemaArgs = schemaFiles.join(' ');
    const command = `npx quicktype ${schemaArgs} ` +
      `-o ${OUTPUT_FILE} ` +
      `--lang typescript ` +
      `--src-lang schema ` +
      `--just-types ` +
      `--prefer-unions ` +
      `--acronym-style original ` +
      `--nice-property-names ` +
      `--prefer-const-values`;

    // Run quicktype
    execSync(command, { stdio: 'inherit' });

    // Add header comment to generated file
    addHeaderComment();

    console.log('✓ TypeScript types generated successfully');
    console.log(`  Output: ${OUTPUT_FILE}`);
  } catch (error) {
    console.error('✗ Failed to generate TypeScript types');
    console.error(error.message);
    process.exit(1);
  }
}

/**
 * Add header comment to generated file
 */
function addHeaderComment() {
  const generatedCode = readFileSync(OUTPUT_FILE, 'utf-8');

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

  writeFileSync(OUTPUT_FILE, header + generatedCode);
}

/**
 * Main function
 */
function main() {
  try {
    const schemaFiles = findSchemaFiles();
    generateTypes(schemaFiles);
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
