import json
from pathlib import Path

import anthropic

from config import CLAUDE_API_KEY

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

# Load playbook
playbook_path = Path(__file__).parent / "prompts" / "playbook.json"
with open(playbook_path) as f:
    PLAYBOOK = json.load(f)

# Load base prompt
prompt_path = Path(__file__).parent / "prompts" / "base_prompt.txt"
with open(prompt_path) as f:
    BASE_PROMPT = f.read()


async def generate_suggestion(investor_text: str, context: list) -> dict | None:
    """Generate AI suggestion for investor question."""

    # Build context (last 10 exchanges)
    recent = context[-10:]
    context_str = "\n".join([f"{c.get('speaker')}: {c.get('text')}" for c in recent])

    prompt = f"""{BASE_PROMPT}

INVESTOR JUST SAID: "{investor_text}"

RECENT CONVERSATION:
{context_str}

PLAYBOOK:
{json.dumps(PLAYBOOK, indent=2)}

Generate ONE suggestion (max 15 words). Return JSON only:
{{
    "text": "your suggestion",
    "confidence": 0.0-1.0,
    "priority": "high/medium/low",
    "reasoning": "why"
}}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        suggestion = json.loads(response.content[0].text)
        suggestion["type"] = "suggestion"
        return suggestion

    except Exception as e:  # pragma: no cover - debug logging only
        print(f"AI Error: {e}")
        return None

