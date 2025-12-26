# AI Agents Module

## Overview
AI-powered agents for marketing and content generation using LangChain and OpenAI.

## Agents

### Creative Strategist Agent
Analyzes target audience and generates creative hooks:
- FOMO (Fear of Missing Out)
- Problem/Solution
- Social Proof
- Curiosity Gap
- Before/After Transformation

### Copywriter Agent
Writes Meta-specific ad copy:
- Primary Text (125-500 chars)
- Headlines (40-255 chars)
- Descriptions (30-125 chars)
- CTA selection

### Visual Director Agent
Creates visual content prompts:
- DALL-E/Midjourney image prompts
- Video concepts with shot breakdowns
- Style and mood specifications

## Usage
```python
from modules.agents import CreativeStrategistAgent, CopywriterAgent, VisualDirectorAgent

strategist = CreativeStrategistAgent()
angles = await strategist.generate_angles(campaign)
```

## Dependencies
- langchain-openai
- OpenAI GPT-4o model
