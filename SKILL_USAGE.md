# How to Use the /mpy-review Skill

## Important: Skills are Invoked BY Claude

You **cannot** type `/mpy-review` directly as a command. Instead, you **ask Claude** to use the skill for you.

## Usage Patterns

### ❌ This Doesn't Work
```
/mpy-review the current branch
```
This will show an error: "This slash command can only be invoked by Claude, not directly by users."

### ✅ These Work

#### Ask Claude Naturally
```
Can you review my current branch?
```
Claude will recognize the intent and invoke the skill.

#### Ask Claude to Use the Skill Explicitly
```
Can you /mpy-review the current branch?
```
Explicitly tells Claude to use the mpy-review skill.

## Example Conversations

### Review Current Work
```
You: Can you review my current branch?

Claude: ● /mpy-review
I'll review your current branch using dpgeorge's review patterns.
[runs: git diff main | mpy-review-rag review --stdin --codebase --output prompt]
[provides dpgeorge-style review feedback]
```

### Review Specific Commit
```
You: Can you review commit ca65d543?

Claude: ● /mpy-review
I'll review commit ca65d543.
[runs: git show ca65d543 | mpy-review-rag review --stdin --codebase --output prompt]
[provides review feedback]
```

### Review Specific Files
```
You: Can you review my changes to py/gc.c?

Claude: ● /mpy-review
I'll review your changes to py/gc.c.
[runs: git diff main -- py/gc.c | mpy-review-rag review --stdin --output prompt]
[provides targeted review for that file]
```

### Find Review Examples
```
You: What has dpgeorge said about memory allocation?

Claude: ● /mpy-review
I'll search for dpgeorge's feedback on memory allocation.
[runs: mpy-review-rag search "memory allocation" --domain memory -k 10]
[presents relevant review examples]
```

### Quick Check
```
You: Can you /mpy-review stats?

Claude: ● /mpy-review
[runs: mpy-review-rag stats]
Index exists: True
Number of records: 18,614
```

## Natural Language Variations

Claude understands many natural phrasings:

**For Reviews:**
- "Can you review my current changes?"
- "Review this branch please"
- "What would dpgeorge think of my changes?"
- "Can you give me feedback on my code?"

**For Examples:**
- "Find examples of GPIO reviews"
- "Show me what dpgeorge has said about error handling"
- "What are common patterns for memory management?"

**Explicit Skill Invocation:**
- "Can you /mpy-review the current branch?"
- "Can you /mpy-review commit abc123?"
- "Can you /mpy-review my changes to extmod/network.c?"

## What Happens Behind the Scenes

When you ask Claude to review code, the skill agent:

1. **Parses your intent** - Understands what you want reviewed
2. **Generates the diff** - Runs appropriate git command (diff, show, etc.)
3. **Invokes the tool** - Pipes to `/home/anl/mpy/dpgeorge-review-db/venv/bin/mpy-review-rag`
4. **Chooses options** - Selects --codebase, --rerank, output format based on context
5. **Presents results** - Provides dpgeorge-style review feedback conversationally

## Tips

1. **Be specific** - "Review commit abc123" is clearer than "review my code"
2. **Mention scope** - "Review my changes to py/gc.c" focuses the review
3. **Ask for examples** - "What has dpgeorge said about..." gets relevant patterns
4. **Try natural language** - Claude understands intent, you don't need exact phrasing

## Common Requests

| What You Want | What You Say |
|---------------|-------------|
| Review current work | "Can you review my current branch?" |
| Review uncommitted | "Review my uncommitted changes" |
| Review commit | "Can you review commit abc123?" |
| Review specific file | "Review my changes to py/gc.c" |
| Review PR | "Can you review PR 12345?" |
| Find patterns | "What has dpgeorge said about memory leaks?" |
| Get examples | "Find examples of API design reviews" |
| Check status | "Can you /mpy-review stats?" |

## Troubleshooting

### "This slash command can only be invoked by Claude"
You tried to type `/mpy-review` directly. Instead, ask Claude:
```
Can you /mpy-review the current branch?
```

### "Index not found"
The review database hasn't been built. Run:
```bash
cd /home/anl/mpy/dpgeorge-review-db
source venv/bin/activate
python scripts/build_index_resume.py
```

### No response from skill
Make sure you're in a git repository with MicroPython code. The skill needs to be able to run git commands.

## Summary

**Remember:** You don't invoke `/mpy-review` directly. You **ask Claude** to use it for you.

The magic word is: **"Can you..."**
