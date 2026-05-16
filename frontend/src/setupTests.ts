import { TextDecoder, TextEncoder } from 'util';

const testGlobal = globalThis as typeof globalThis & {
    IS_REACT_ACT_ENVIRONMENT?: boolean;
};

testGlobal.IS_REACT_ACT_ENVIRONMENT = true;

await import('@testing-library/jest-dom/vitest');

if (!globalThis.TextEncoder) {
    Object.defineProperty(globalThis, 'TextEncoder', { value: TextEncoder });
}

if (!globalThis.TextDecoder) {
    Object.defineProperty(globalThis, 'TextDecoder', { value: TextDecoder });
}

const storage = new Map<string, string>();
const localStorageMock: Storage = {
    get length() {
        return storage.size;
    },
    clear: () => storage.clear(),
    getItem: (key: string) => storage.get(key) ?? null,
    key: (index: number) => Array.from(storage.keys())[index] ?? null,
    removeItem: (key: string) => {
        storage.delete(key);
    },
    setItem: (key: string, value: string) => {
        storage.set(key, value);
    },
};

Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageMock,
    configurable: true,
    writable: true,
});

if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'localStorage', {
        value: localStorageMock,
        configurable: true,
    });
}

// Silence specific benign deprecation warnings in the test environment
const originalError = console.error;
const originalWarn = console.warn;

console.error = (...args) => {
    // Silence the act() deprecation warning from @testing-library/react v13
    if (typeof args[0] === 'string' && /ReactDOMTestUtils.act/.test(args[0])) {
        return;
    }
    if (
        typeof args[0] === 'string' &&
        /testing environment is not configured to support act/.test(args[0])
    ) {
        return;
    }
    originalError(...args);
};

console.warn = (...args) => {
    // Silence React Router v7 future flag warnings
    if (typeof args[0] === 'string' && /React Router Future Flag Warning/.test(args[0])) {
        return;
    }
    originalWarn(...args);
};
