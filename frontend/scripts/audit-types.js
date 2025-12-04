#!/usr/bin/env node
/**
 * Audit manual type usage across the frontend codebase
 *
 * This script identifies:
 * - Which manual types can be replaced with generated types
 * - Which types are client-only and should remain
 * - Usage frequency of each type
 * - Import locations for migration
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, relative } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const SRC_DIR = join(__dirname, '../src');
const TYPES_FILE = join(__dirname, '../src/types/index.ts');
const GENERATED_TYPES_FILE = join(__dirname, '../src/types/generated/api.ts');

// Types that exist in both manual and generated
const MAPPABLE_TYPES = {
  // Manual type -> Generated type
  'User': 'UserProfile',
  'UserStatus': 'UserStatus',
  'Message': 'Message',
  'Topic': 'Topic',
  'Session': 'Session',
  'TherapyPlan': 'TherapyPlan',
  'WorkflowNextAction': 'WorkflowNextActionResponse',
};

// Types that are client-only (UI state, not API models)
const CLIENT_ONLY_TYPES = [
  'AgentType',
  'TherapyStyle',
  'SessionStatus',
  'AppState',
  'ApiResponse',
  'LocalStorageData',
  'UserPreferences',
  'TherapyStyleInfo',
];

/**
 * Find all TypeScript files in a directory
 */
function findTsFiles(dir, files = []) {
  const entries = readdirSync(dir);

  for (const entry of entries) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);

    if (stat.isDirectory()) {
      // Skip node_modules, dist, generated
      if (!['node_modules', 'dist', 'generated', 'coverage'].includes(entry)) {
        findTsFiles(fullPath, files);
      }
    } else if (entry.endsWith('.ts') || entry.endsWith('.tsx')) {
      // Skip the types files themselves
      if (!fullPath.includes('types/index.ts') && !fullPath.includes('types/generated')) {
        files.push(fullPath);
      }
    }
  }

  return files;
}

/**
 * Extract type imports from a file
 */
function extractTypeImports(filePath) {
  const content = readFileSync(filePath, 'utf-8');
  const imports = [];

  // Match: import { Type1, Type2 } from '@/types'
  const importRegex = /import\s+(?:type\s+)?{([^}]+)}\s+from\s+['"]@?\/types['"]/g;
  let match;

  while ((match = importRegex.exec(content)) !== null) {
    const typesStr = match[1];
    const types = typesStr.split(',').map(t => t.trim());
    imports.push(...types);
  }

  return imports;
}

/**
 * Count type usage in a file
 */
function countTypeUsage(filePath, typeName) {
  const content = readFileSync(filePath, 'utf-8');

  // Count occurrences (excluding in comments)
  const lines = content.split('\n').filter(line => !line.trim().startsWith('//'));
  const cleanContent = lines.join('\n');

  const regex = new RegExp(`\\b${typeName}\\b`, 'g');
  const matches = cleanContent.match(regex);

  return matches ? matches.length : 0;
}

/**
 * Main audit function
 */
function auditTypes() {
  console.log('📊 Frontend Type Usage Audit\n');
  console.log('='  .repeat(60));

  const tsFiles = findTsFiles(SRC_DIR);
  console.log(`Analyzing ${tsFiles.length} TypeScript files...\n`);

  // Extract all manual types
  const manualTypesContent = readFileSync(TYPES_FILE, 'utf-8');
  const manualTypeRegex = /export\s+(?:interface|enum|type)\s+(\w+)/g;
  const manualTypes = [];
  let match;

  while ((match = manualTypeRegex.exec(manualTypesContent)) !== null) {
    manualTypes.push(match[1]);
  }

  console.log('📝 Manual Types Found:', manualTypes.length);
  console.log('   ', manualTypes.join(', '));
  console.log();

  // Analyze each type
  const results = {
    mappable: [],
    clientOnly: [],
    unused: [],
  };

  for (const typeName of manualTypes) {
    let totalUsage = 0;
    const usageByFile = [];

    for (const file of tsFiles) {
      const usage = countTypeUsage(file, typeName);
      if (usage > 0) {
        totalUsage += usage;
        usageByFile.push({
          file: relative(SRC_DIR, file),
          count: usage,
        });
      }
    }

    const typeInfo = {
      name: typeName,
      totalUsage,
      usageByFile,
    };

    if (typeName in MAPPABLE_TYPES) {
      typeInfo.generatedType = MAPPABLE_TYPES[typeName];
      results.mappable.push(typeInfo);
    } else if (CLIENT_ONLY_TYPES.includes(typeName)) {
      results.clientOnly.push(typeInfo);
    } else if (totalUsage === 0) {
      results.unused.push(typeInfo);
    } else {
      // Unknown type - might need investigation
      results.clientOnly.push(typeInfo);
    }
  }

  // Print results
  console.log('='  .repeat(60));
  console.log('🔄 MAPPABLE TYPES (Can use generated types)');
  console.log('='  .repeat(60));

  if (results.mappable.length === 0) {
    console.log('   None found');
  } else {
    for (const type of results.mappable) {
      console.log(`\n${type.name} → ${type.generatedType}`);
      console.log(`   Total usage: ${type.totalUsage}`);
      console.log(`   Used in ${type.usageByFile.length} files:`);
      for (const usage of type.usageByFile.slice(0, 5)) {
        console.log(`     - ${usage.file} (${usage.count}x)`);
      }
      if (type.usageByFile.length > 5) {
        console.log(`     ... and ${type.usageByFile.length - 5} more files`);
      }
    }
  }

  console.log('\n' + '='  .repeat(60));
  console.log('🎨 CLIENT-ONLY TYPES (Keep as-is)');
  console.log('='  .repeat(60));

  if (results.clientOnly.length === 0) {
    console.log('   None found');
  } else {
    for (const type of results.clientOnly) {
      console.log(`\n${type.name}`);
      console.log(`   Total usage: ${type.totalUsage}`);
      console.log(`   Used in ${type.usageByFile.length} files`);
    }
  }

  console.log('\n' + '='  .repeat(60));
  console.log('🗑️  UNUSED TYPES');
  console.log('='  .repeat(60));

  if (results.unused.length === 0) {
    console.log('   None found (all types are used)');
  } else {
    console.log('   ' + results.unused.map(t => t.name).join(', '));
  }

  console.log('\n' + '='  .repeat(60));
  console.log('📈 SUMMARY');
  console.log('='  .repeat(60));
  console.log(`Total manual types: ${manualTypes.length}`);
  console.log(`Mappable to generated: ${results.mappable.length}`);
  console.log(`Client-only: ${results.clientOnly.length}`);
  console.log(`Unused: ${results.unused.length}`);

  const totalUsage = [...results.mappable, ...results.clientOnly]
    .reduce((sum, t) => sum + t.totalUsage, 0);
  console.log(`Total type usages: ${totalUsage}`);

  console.log('\n' + '='  .repeat(60));
  console.log('✅ MIGRATION RECOMMENDATIONS');
  console.log('='  .repeat(60));

  if (results.mappable.length > 0) {
    console.log('\n1. Create compatibility layer in types/index.ts:');
    console.log('   Import generated types and re-export with aliases');
    console.log();
    console.log('2. Gradually update imports:');
    console.log('   Replace manual types with generated ones');
    console.log();
    console.log('3. Remove unused types:');
    if (results.unused.length > 0) {
      console.log('   ', results.unused.map(t => t.name).join(', '));
    } else {
      console.log('   None to remove');
    }
  } else {
    console.log('\nNo mappable types found. All types are either client-only or unused.');
  }

  console.log();

  return results;
}

// Run audit
try {
  auditTypes();
} catch (error) {
  console.error('Error running audit:', error);
  process.exit(1);
}
