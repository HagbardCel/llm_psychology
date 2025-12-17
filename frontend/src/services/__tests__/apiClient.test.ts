import { ApiClient, ApiRequestError } from '../apiClient';

describe('ApiClient', () => {
  let client: ApiClient;
  let originalFetch: typeof global.fetch;

  beforeEach(() => {
    client = new ApiClient({ baseUrl: 'http://test.example.com' });
    originalFetch = global.fetch;
    global.fetch = jest.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  describe('GET requests', () => {
    it('should make successful GET request', async () => {
      const mockData = { status: 'ok', data: 'test' };
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
        headers: new Headers({ 'content-type': 'application/json' })
      });

      const result = await client.get('/health');

      expect(result).toEqual(mockData);
      expect(global.fetch).toHaveBeenCalledWith(
        'http://test.example.com/health',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({
            'Content-Type': 'application/json'
          })
        })
      );
    });

    it('should handle non-JSON responses', async () => {
      const mockText = 'Plain text response';
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        text: async () => mockText,
        headers: new Headers({ 'content-type': 'text/plain' })
      });

      const result = await client.get('/text-endpoint');

      expect(result).toBe(mockText);
    });
  });

  describe('POST requests', () => {
    it('should make successful POST request with data', async () => {
      const requestData = { name: 'John', age: 30 };
      const mockResponse = { id: '123', ...requestData };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
        headers: new Headers({ 'content-type': 'application/json' })
      });

      const result = await client.post('/users', requestData);

      expect(result).toEqual(mockResponse);
      expect(global.fetch).toHaveBeenCalledWith(
        'http://test.example.com/users',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(requestData)
        })
      );
    });

    it('should handle POST request without data', async () => {
      const mockResponse = { success: true };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
        headers: new Headers({ 'content-type': 'application/json' })
      });

      const result = await client.post('/action');

      expect(result).toEqual(mockResponse);
      expect(global.fetch).toHaveBeenCalledWith(
        'http://test.example.com/action',
        expect.objectContaining({
          method: 'POST',
          body: undefined
        })
      );
    });
  });

  describe('Error handling', () => {
    it('should throw ApiRequestError on HTTP 404', async () => {
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({ detail: 'Resource not found' }),
        headers: new Headers({ 'content-type': 'application/json' })
      });

      await expect(client.get('/nonexistent')).rejects.toThrow(ApiRequestError);

      // Reset mock for second call
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({ detail: 'Resource not found' }),
        headers: new Headers({ 'content-type': 'application/json' })
      });

      await expect(client.get('/nonexistent')).rejects.toThrow('HTTP 404: Not Found');
    });

    it('should throw ApiRequestError on HTTP 500 with error body', async () => {
      const errorBody = { error: 'Internal server error', code: 'SERVER_ERROR' };
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => errorBody,
        headers: new Headers({ 'content-type': 'application/json' })
      });

      try {
        await client.get('/error');
        fail('Should have thrown ApiRequestError');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiRequestError);
        const apiError = error as ApiRequestError;
        expect(apiError.status).toBe(500);
        expect(apiError.statusText).toBe('Internal Server Error');
        expect(apiError.body).toEqual(errorBody);
      }
    });

    it('should handle error response with text body', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: async () => {
          throw new Error('Not JSON');
        },
        text: async () => 'Invalid request format',
        headers: new Headers({ 'content-type': 'text/plain' })
      });

      try {
        await client.get('/bad-request');
        fail('Should have thrown ApiRequestError');
      } catch (error) {
        expect(error).toBeInstanceOf(ApiRequestError);
        const apiError = error as ApiRequestError;
        expect(apiError.body).toBe('Invalid request format');
      }
    });

    it('should handle network errors', async () => {
      (global.fetch as jest.Mock).mockRejectedValueOnce(
        new Error('Network connection failed')
      );

      await expect(client.get('/endpoint')).rejects.toThrow(
        'Network error: Network connection failed'
      );
    });

    it('should handle timeout by passing abort signal to fetch', async () => {
      const slowClient = new ApiClient({
        baseUrl: 'http://test.example.com',
        timeout: 100
      });

      (global.fetch as jest.Mock).mockImplementationOnce(
        (_url, options) => {
          // Verify that abort signal is passed
          expect(options.signal).toBeDefined();
          expect(options.signal).toBeInstanceOf(AbortSignal);

          // Simulate abort error
          throw new DOMException('The user aborted a request.', 'AbortError');
        }
      );

      await expect(slowClient.get('/slow')).rejects.toThrow('Request timeout after 100ms');
    });
  });

  describe('Custom headers', () => {
    it('should merge custom headers with default headers', async () => {
      const customClient = new ApiClient({
        baseUrl: 'http://test.example.com',
        headers: {
          'Authorization': 'Bearer token123',
          'X-Custom-Header': 'custom-value'
        }
      });

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
        headers: new Headers({ 'content-type': 'application/json' })
      });

      await customClient.get('/protected');

      expect(global.fetch).toHaveBeenCalledWith(
        'http://test.example.com/protected',
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
            'Authorization': 'Bearer token123',
            'X-Custom-Header': 'custom-value'
          })
        })
      );
    });
  });

  describe('Other HTTP methods', () => {
    it('should make PUT request', async () => {
      const data = { name: 'Updated' };
      const mockResponse = { id: '123', ...data };

      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
        headers: new Headers({ 'content-type': 'application/json' })
      });

      const result = await client.put('/users/123', data);

      expect(result).toEqual(mockResponse);
      expect(global.fetch).toHaveBeenCalledWith(
        'http://test.example.com/users/123',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify(data)
        })
      );
    });

    it('should make DELETE request', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
        headers: new Headers({ 'content-type': 'application/json' })
      });

      const result = await client.delete('/users/123');

      expect(result).toEqual({ success: true });
      expect(global.fetch).toHaveBeenCalledWith(
        'http://test.example.com/users/123',
        expect.objectContaining({
          method: 'DELETE'
        })
      );
    });
  });

  describe('Base URL configuration', () => {
    it('should use provided base URL', () => {
      const customClient = new ApiClient({ baseUrl: 'http://custom.com' });
      expect(customClient['baseUrl']).toBe('http://custom.com');
    });

    it('should fall back to localhost:8000 when no base URL provided', () => {
      const defaultClient = new ApiClient({ baseUrl: '' });
      expect(defaultClient['baseUrl']).toBe('http://localhost:8000');
    });
  });
});
