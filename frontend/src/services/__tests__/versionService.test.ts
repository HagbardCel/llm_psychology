/**
 * Unit tests for version service
 */

import type { Mock } from 'vitest';

import {
  CLIENT_VERSION,
  CLIENT_TYPE,
  parseVersion,
  compareVersions,
  getBackendVersion,
  checkVersionCompatibility,
  performVersionCheck,
} from '../versionService';

const mockJsonHeaders = {
  get: (name: string) => (name.toLowerCase() === 'content-type' ? 'application/json' : null),
};

describe('versionService', () => {
  describe('constants', () => {
    it('should have valid CLIENT_VERSION', () => {
      expect(CLIENT_VERSION).toBeDefined();
      expect(CLIENT_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
    });

    it('should have valid CLIENT_TYPE', () => {
      expect(CLIENT_TYPE).toBe('web');
    });
  });

  describe('parseVersion', () => {
    it('should parse valid version string', () => {
      const version = parseVersion('1.2.3');
      expect(version).toEqual({ major: 1, minor: 2, patch: 3 });
    });

    it('should throw error for invalid version format', () => {
      expect(() => parseVersion('1.2')).toThrow('Invalid version format');
      expect(() => parseVersion('invalid')).toThrow();
      expect(() => parseVersion('1.2.3.4')).toThrow('Invalid version format');
    });

    it('should handle zero versions', () => {
      const version = parseVersion('0.0.0');
      expect(version).toEqual({ major: 0, minor: 0, patch: 0 });
    });
  });

  describe('compareVersions', () => {
    it('should return 0 for equal versions', () => {
      expect(compareVersions('1.2.3', '1.2.3')).toBe(0);
      expect(compareVersions('0.0.0', '0.0.0')).toBe(0);
    });

    it('should return positive for newer version', () => {
      expect(compareVersions('1.2.3', '1.2.2')).toBeGreaterThan(0);
      expect(compareVersions('1.3.0', '1.2.9')).toBeGreaterThan(0);
      expect(compareVersions('2.0.0', '1.9.9')).toBeGreaterThan(0);
    });

    it('should return negative for older version', () => {
      expect(compareVersions('1.2.2', '1.2.3')).toBeLessThan(0);
      expect(compareVersions('1.2.9', '1.3.0')).toBeLessThan(0);
      expect(compareVersions('1.9.9', '2.0.0')).toBeLessThan(0);
    });

    it('should prioritize major version', () => {
      expect(compareVersions('2.0.0', '1.9.9')).toBeGreaterThan(0);
    });

    it('should prioritize minor version over patch', () => {
      expect(compareVersions('1.3.0', '1.2.9')).toBeGreaterThan(0);
    });
  });

  describe('getBackendVersion', () => {
    beforeEach(() => {
      global.fetch = vi.fn();
    });

    afterEach(() => {
      vi.resetAllMocks();
    });

    it('should fetch version info successfully', async () => {
      const mockResponse = {
        api_version: '1.0.0',
        min_client_version: '1.0.0',
        server_time: '2025-12-03T10:00:00Z',
      };

      (global.fetch as Mock).mockResolvedValue({
        ok: true,
        headers: mockJsonHeaders,
        json: async () => mockResponse,
      });

      const result = await getBackendVersion();

      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/version',
        expect.objectContaining({
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
        })
      );
      expect(result).toEqual(mockResponse);
    });

    it('should use custom base URL when provided', async () => {
      (global.fetch as Mock).mockResolvedValue({
        ok: true,
        headers: mockJsonHeaders,
        json: async () => ({ api_version: '1.0.0', min_client_version: '1.0.0', server_time: '' }),
      });

      await getBackendVersion('http://example.com');

      expect(global.fetch).toHaveBeenCalledWith(
        'http://example.com/api/version',
        expect.objectContaining({
          method: 'GET',
        })
      );
    });

    it('should throw error on fetch failure', async () => {
      (global.fetch as Mock).mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        headers: mockJsonHeaders,
        json: async () => ({ error: 'boom' }),
        text: async () => '{"error":"boom"}',
      });

      await expect(getBackendVersion()).rejects.toThrow('Failed to get version info: 500');
    });
  });

  describe('checkVersionCompatibility', () => {
    beforeEach(() => {
      global.fetch = vi.fn();
    });

    afterEach(() => {
      vi.resetAllMocks();
    });

    it('should check version compatibility successfully', async () => {
      const mockResponse = {
        compatible: true,
        api_version: '1.0.0',
        client_version: '1.0.0',
        message: 'Versions are compatible',
        upgrade_required: false,
        upgrade_recommended: false,
      };

      (global.fetch as Mock).mockResolvedValue({
        ok: true,
        headers: mockJsonHeaders,
        json: async () => mockResponse,
      });

      const result = await checkVersionCompatibility();

      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8000/api/version/check',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            client_version: CLIENT_VERSION,
            client_type: CLIENT_TYPE,
          }),
        })
      );
      expect(result).toEqual(mockResponse);
    });

    it('should handle incompatible version response', async () => {
      const mockResponse = {
        compatible: false,
        api_version: '2.0.0',
        client_version: '1.0.0',
        message: 'Version incompatible',
        upgrade_required: true,
        upgrade_recommended: false,
      };

      (global.fetch as Mock).mockResolvedValue({
        ok: true,
        headers: mockJsonHeaders,
        json: async () => mockResponse,
      });

      const result = await checkVersionCompatibility();

      expect(result.compatible).toBe(false);
      expect(result.upgrade_required).toBe(true);
    });

    it('should throw error on fetch failure', async () => {
      (global.fetch as Mock).mockResolvedValue({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        headers: mockJsonHeaders,
        json: async () => ({ error: 'bad request' }),
        text: async () => '{"error":"bad request"}',
      });

      await expect(checkVersionCompatibility()).rejects.toThrow('Failed to check version: 400');
    });
  });

  describe('performVersionCheck', () => {
    beforeEach(() => {
      global.fetch = vi.fn();
      vi.spyOn(console, 'error').mockImplementation(() => {});
    });

    afterEach(() => {
      vi.resetAllMocks();
    });

    it('should return error severity for incompatible version', async () => {
      (global.fetch as Mock).mockResolvedValue({
        ok: true,
        headers: mockJsonHeaders,
        json: async () => ({
          compatible: false,
          api_version: '2.0.0',
          client_version: '1.0.0',
          message: 'Version incompatible',
          upgrade_required: true,
          upgrade_recommended: false,
        }),
      });

      const result = await performVersionCheck();

      expect(result.compatible).toBe(false);
      expect(result.severity).toBe('error');
      expect(result.message).toContain('incompatible');
    });

    it('should return warning severity for outdated version', async () => {
      (global.fetch as Mock).mockResolvedValue({
        ok: true,
        headers: mockJsonHeaders,
        json: async () => ({
          compatible: true,
          api_version: '1.2.0',
          client_version: '1.0.0',
          message: 'Version is outdated',
          upgrade_required: false,
          upgrade_recommended: true,
        }),
      });

      const result = await performVersionCheck();

      expect(result.compatible).toBe(true);
      expect(result.severity).toBe('warning');
      expect(result.message).toContain('outdated');
    });

    it('should return info severity for compatible version', async () => {
      (global.fetch as Mock).mockResolvedValue({
        ok: true,
        headers: mockJsonHeaders,
        json: async () => ({
          compatible: true,
          api_version: '1.0.0',
          client_version: '1.0.0',
          message: 'Versions are compatible',
          upgrade_required: false,
          upgrade_recommended: false,
        }),
      });

      const result = await performVersionCheck();

      expect(result.compatible).toBe(true);
      expect(result.severity).toBe('info');
    });

    it('should handle fetch errors gracefully', async () => {
      (global.fetch as Mock).mockRejectedValue(new Error('Network error'));

      const result = await performVersionCheck();

      // Should allow continuation on error
      expect(result.compatible).toBe(true);
      expect(result.severity).toBe('warning');
      expect(result.message).toContain('Could not verify');
      expect(console.error).toHaveBeenCalled();
    });
  });
});
