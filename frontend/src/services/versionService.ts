/**
 * Version checking service for web frontend.
 *
 * Verifies compatibility with backend API version before starting the app.
 */

import { ApiClient, ApiRequestError, apiClient } from './apiClient';

// Frontend client version (should match backend API version format)
export const CLIENT_VERSION = '1.0.0';
export const CLIENT_TYPE = 'web';

/**
 * Version information from backend
 */
export interface VersionInfo {
  api_version: string;
  min_client_version: string;
  server_time: string;
}

/**
 * Version compatibility check result
 */
export interface VersionCheckResult {
  compatible: boolean;
  api_version: string;
  client_version: string;
  message: string;
  upgrade_required: boolean;
  upgrade_recommended: boolean;
}

function getClient(baseUrl: string): ApiClient {
  return baseUrl ? new ApiClient({ baseUrl }) : apiClient;
}

/**
 * Get version information from backend
 */
export async function getBackendVersion(baseUrl: string = ''): Promise<VersionInfo> {
  try {
    return await getClient(baseUrl).get<VersionInfo>('/api/version');
  } catch (error) {
    if (error instanceof ApiRequestError) {
      throw new Error(`Failed to get version info: ${error.status} ${error.statusText}`, { cause: error });
    }
    throw error;
  }
}

/**
 * Check version compatibility with backend
 */
export async function checkVersionCompatibility(
  baseUrl: string = ''
): Promise<VersionCheckResult> {
  try {
    return await getClient(baseUrl).post<VersionCheckResult>('/api/version/check', {
      client_version: CLIENT_VERSION,
      client_type: CLIENT_TYPE,
    });
  } catch (error) {
    if (error instanceof ApiRequestError) {
      throw new Error(`Failed to check version: ${error.status} ${error.statusText}`, { cause: error });
    }
    throw error;
  }
}

/**
 * Perform version check and return compatibility status
 *
 * @returns Object with compatible status and user-friendly message
 */
export async function performVersionCheck(
  baseUrl: string = ''
): Promise<{ compatible: boolean; message: string; severity: 'error' | 'warning' | 'info' }> {
  try {
    const result = await checkVersionCompatibility(baseUrl);

    if (!result.compatible) {
      return {
        compatible: false,
        message: result.message,
        severity: 'error',
      };
    }

    if (result.upgrade_recommended) {
      return {
        compatible: true,
        message: result.message,
        severity: 'warning',
      };
    }

    return {
      compatible: true,
      message: result.message,
      severity: 'info',
    };
  } catch (error) {
    console.error('Version check failed:', error);
    return {
      compatible: true, // Allow continuation on error
      message: `Could not verify version compatibility: ${error instanceof Error ? error.message : 'Unknown error'}`,
      severity: 'warning',
    };
  }
}

/**
 * Parse semantic version string into components
 */
export function parseVersion(versionStr: string): { major: number; minor: number; patch: number } {
  const parts = versionStr.split('.');
  if (parts.length !== 3) {
    throw new Error(`Invalid version format: ${versionStr}`);
  }

  return {
    major: parseInt(parts[0], 10),
    minor: parseInt(parts[1], 10),
    patch: parseInt(parts[2], 10),
  };
}

/**
 * Compare two semantic versions
 *
 * @returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2
 */
export function compareVersions(v1: string, v2: string): number {
  const version1 = parseVersion(v1);
  const version2 = parseVersion(v2);

  if (version1.major !== version2.major) {
    return version1.major - version2.major;
  }

  if (version1.minor !== version2.minor) {
    return version1.minor - version2.minor;
  }

  return version1.patch - version2.patch;
}
