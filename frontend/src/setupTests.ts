import '@testing-library/jest-dom';

// Silence specific benign deprecation warnings in the test environment
const originalError = console.error;
const originalWarn = console.warn;

console.error = (...args) => {
    // Silence the act() deprecation warning from @testing-library/react v13
    if (typeof args[0] === 'string' && /ReactDOMTestUtils.act/.test(args[0])) {
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
