# Virtual LLM-Driven Psychoanalyst App

This application provides a virtual psychoanalyst experience, running locally in your terminal. It uses Large Language Models (LLMs) and a Retrieval-Augmented Generation (RAG) system to provide context-aware, personalized conversations.

## Features

- **Local & Private:** All data is stored locally on your machine.
- **Dockerized:** Easy setup and consistent environment.
- **Domain Knowledge RAG:** Utilizes a curated knowledge base of psychological theories.
- **Sequential Agent Workflow:** Employs distinct agents for intake, conversation, and reflection.

## Getting Started

### Prerequisites

- Docker and Docker Compose
- A Google Gemini API key (for now)

### Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd psychoanalyst_app
    ```

2.  **Configure Environment Variables:**
    Create a `.env` file in the project root and add your API key:
    ```env
    GOOGLE_API_KEY=your_actual_google_gemini_api_key_here
    ```
    **Important:** Replace `your_actual_google_gemini_api_key_here` with your real Google Gemini API key. You can get one from [Google AI Studio](https://aistudio.google.com/).

3.  **Build and Run with Docker:**
    ```bash
    docker-compose up --build
    ```

4.  **For Interactive Mode (to actually use the app):**
    ```bash
    docker-compose run --rm app python src/main.py
    ```

## Project Structure

```
psychoanalyst_app/
├── src/
│   ├── main.py                     # Main application entry point
│   ├── config.py                   # Configuration settings
│   ├── agents/
│   │   ├── intake_agent.py         # Handles initial user interaction
│   │   ├── psychoanalyst_agent.py  # Core conversational logic
│   │   └── reflection_agent.py     # Designs and refines the therapy plan
│   ├── services/
│   │   ├── llm_service.py          # Abstraction for LLM API calls
│   │   ├── db_service.py           # Handles all SQLite database operations
│   │   └── rag_service.py          # Orchestrates domain knowledge RAG
│   ├── utils/
│   │   ├── data_models.py          # Pydantic models for session data, plans, etc.
│   │   └── embedding_utils.py      # Functions for text embedding
│   └── data/
│       ├── domain_knowledge/       # Raw text files for psychological RAG
│       ├── vector_db/              # Local persistence for the vector database
│       └── psychoanalyst.db        # SQLite database file
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

## How It Works

1.  **Initialization:** The application loads configuration, initializes services, and checks for an existing therapy plan.
2.  **Intake (First Run):** If no plan exists, the `IntakeAgent` gathers baseline information.
3.  **Reflection:** The `ReflectionAgent` analyzes the intake and creates the initial therapy plan.
4.  **Session Loop:**
    - The `PsychoanalystAgent` conducts the conversation, guided by the plan and domain knowledge RAG.
    - After the session, the `ReflectionAgent` updates the therapy plan based on the new conversation.
5.  **Data Persistence:** Sessions and therapy plans are stored in a local SQLite database.

## Development

This project is still under active development. See `llm_psychologist.md` for the detailed implementation plan and roadmap.

### Running Tests

```bash
docker-compose run --rm app python -m pytest tests/
```

### Local Development (without Docker)

1.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up environment variables:**
    Create a `.env` file with your API key.

4.  **Run the application:**
    ```bash
    python src/main.py
    ```

## Troubleshooting

- **API Key Error:** Make sure you have a valid Google Gemini API key in your `.env` file.
- **Docker Permission Issues:** Make sure you have proper permissions to run Docker commands.
- **Port Conflicts:** If you see port conflicts, modify the `docker-compose.yml` file.
