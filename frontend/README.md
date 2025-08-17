# Psychoanalyst Frontend

A modern React TypeScript application for the Virtual LLM-Driven Psychoanalyst platform.

## Features

- 🖥️ Modern React 18+ with TypeScript
- 📱 Responsive design with Material-UI
- 🔄 Progressive Web App (PWA) capabilities
- 💾 Local storage for offline functionality
- 🎨 Consistent design system
- ♿ Accessibility compliant (WCAG 2.1)

## Quick Start

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run preview` - Preview production build
- `npm run lint` - Run ESLint
- `npm run lint:fix` - Fix ESLint issues
- `npm run type-check` - Run TypeScript type checking
- `npm run test` - Run tests
- `npm run test:watch` - Run tests in watch mode
- `npm run test:coverage` - Run tests with coverage

## Architecture

### Components
- `TherapySession` - Main session interface
- `MessageHistory` - Scrollable message display
- `MessageInput` - Text input with send functionality
- `SessionHeader` - Session info and controls
- `Navigation` - App navigation and routing
- `Dashboard` - Main user dashboard

### State Management
- Context API for global state
- Local storage for persistence
- Type-safe interfaces throughout

### Integration with Backend

The frontend integrates with the Python backend API through:

1. **Dual Interface Support**: The backend supports both terminal and web interfaces
2. **Unified Service Layer**: Same business logic serves both interfaces
3. **API Endpoints**: RESTful APIs for session management, user data, etc.
4. **WebSocket Support**: Real-time communication for therapy sessions

### Running Both Interfaces

**Terminal Interface (Original):**
```bash
cd /app
python src/main.py
```

**Web Interface:**
```bash
# Start backend API server
cd /app
python main_launcher.py web

# In another terminal, start frontend
cd /app/frontend
npm run dev
```

## PWA Features

- Offline functionality
- Install prompt
- Background sync
- Push notifications (future)

## Development

### Project Structure
```
src/
├── components/     # React components
├── contexts/       # React contexts
├── hooks/          # Custom hooks
├── pages/          # Page components
├── services/       # API services
├── types/          # TypeScript types
└── utils/          # Utility functions
```

### Code Standards
- TypeScript strict mode
- ESLint + Prettier
- Jest + React Testing Library
- Material-UI components
- Consistent naming conventions

## Deployment

Build the frontend and serve it alongside the Python backend:

```bash
npm run build
# Serve dist/ directory or integrate with backend static serving
```

## Browser Support

- Chrome/Edge 88+
- Firefox 85+
- Safari 14+

## License

MIT