# Prompt Engineering Guidelines

## Core Principles

### 1. Prompt Structure and Consistency

All prompts should follow a clear, consistent structure:
- **Role Definition**: Clearly define the LLM's role and expertise
- **Context Provision**: Provide relevant background information
- **Task Specification**: Clearly state what the LLM should do
- **Output Format**: Specify the expected format of the response
- **Constraints**: Define any limitations or boundaries

### 2. Style-Specific Prompts

Each therapeutic style (Freud, Jung, CBT, etc.) has its own directory under `src/styles/` containing:
- `description.txt`: Brief overview of the style
- `knowledge.md`: Core theoretical knowledge for RAG
- `{agent}_prompt.txt`: Specific prompts for each agent type

### 3. Dynamic Content Integration

Use consistent placeholder syntax for dynamic content:
- `{user_history}`: Previous session transcripts
- `{therapy_goals}`: Current therapy plan goals
- `{user_input}`: Current user message
- `{style_knowledge}`: Relevant theoretical knowledge

## Best Practices

### 1. Clarity and Specificity
- Use clear, unambiguous language
- Avoid jargon unless it's part of the therapeutic style
- Be specific about the desired output format

### 2. Role Consistency
- Maintain consistent character/persona throughout the session
- Ensure the therapeutic style is clearly reflected
- Avoid switching between different approaches within a session

### 3. Safety and Ethics
- Include guidelines for handling sensitive topics
- Define boundaries for appropriate responses
- Implement crisis detection and referral protocols

### 4. Testing and Validation
- Test prompts with various input scenarios
- Validate output quality and consistency
- Document prompt evolution and rationale

## Prompt Organization

### Directory Structure
```
src/styles/
├── {style_name}/
│   ├── __init__.py
│   ├── description.txt
│   ├── knowledge.md
│   ├── intake_prompt.txt
│   ├── assessment_prompt.txt
│   ├── psychoanalyst_prompt.txt
│   └── reflection_prompt.txt
```

### Loading Mechanism
Use the `StyleService` to load prompts dynamically based on user-selected therapy style. This ensures consistency and makes it easy to add new styles.

## Version Control
- Treat prompts as code - version control all prompt files
- Document significant changes in commit messages
- Consider maintaining prompt changelogs for major revisions
