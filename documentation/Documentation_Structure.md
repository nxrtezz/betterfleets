# Documentation Structure Guidelines

## Purpose

This document provides guidelines for creating API documentation files in the BetterFleet project. It is designed to be readable by humans while also being structured enough for AI agents to understand and follow when creating similar documentation.

## File Structure

Documentation files should be placed in the `/documentation` directory at the project root.

### Naming Convention

- Use descriptive, PascalCase filenames: `API.md`, `DatabaseSchema.md`, `DeploymentGuide.md`
- Use `.md` extension for Markdown files
- Avoid spaces and special characters in filenames

## Document Organization

### 1. Title and Overview

```markdown
# [Document Title]

## Overview
[Brief description of what this document covers and its purpose]
```

- Start with a clear, descriptive title using H1 (`#`)
- Provide an overview section explaining the document's purpose
- Keep the overview concise (2-3 sentences)

### 2. Table of Contents (Optional)

For longer documents (>500 lines), include a table of contents:

```markdown
## Table of Contents

- [Section 1](#section-1)
- [Section 2](#section-2)
- [Section 3](#section-3)
```

### 3. Main Content Sections

Organize content into logical sections using H2 (`##`) and H3 (`###`) headers:

```markdown
## Main Section

### Subsection
Content here...
```

#### Section Guidelines:
- Use H2 for major sections
- Use H3 for subsections within major sections
- Use H4 for detailed subsections (rarely needed)
- Maintain consistent heading hierarchy

### 4. Code Examples

All code examples should be:
- Enclosed in triple backticks with language specification
- Realistic and functional
- Well-commented when complex
- Properly formatted

```markdown
```python
def example_function():
    # This is a comment
    return "example"
```
```

```markdown
```json
{
    "key": "value"
}
```
```

### 5. API Endpoint Documentation

When documenting API endpoints, follow this structure:

```markdown
### Endpoint Name

```
[HTTP_METHOD] /api/endpoint/
```

[Brief description of what the endpoint does]

**Query Parameters:**
- `param1`: Description
- `param2`: Description

**Response:**
```json
[Example response]
```

**Error Responses:**
- `400`: Description
- `404`: Description
```

#### Endpoint Guidelines:
- Use the HTTP method in code format
- Include the full URL path
- Describe query parameters in a bulleted list
- Provide example JSON responses
- Document possible error responses

### 6. Data Models

When documenting data models, use this structure:

```markdown
### ModelName

**Description:** [What this model represents]

**Fields:**
- `field_name` (type): Description
- `field_name` (type): Description

**Relationships:**
- `related_model`: Description of relationship

**Example:**
```json
[Example data]
```
```

### 7. Tables and Lists

Use tables for structured data:

```markdown
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Data 1   | Data 2   | Data 3   |
```

Use lists for:
- Options or choices
- Steps in a process
- Features or capabilities
- Requirements

```markdown
- **Item 1**: Description
- **Item 2**: Description
```

### 8. Notes and Warnings

Use callout blocks for important information:

```markdown
> **Note:** Important information that readers should be aware of

> **Warning:** Critical information that could cause problems if ignored
```

### 9. Code References

When referencing code elements:
- Use backticks for inline code: `function_name()`
- Use backticks for file paths: `/path/to/file.py`
- Use backticks for configuration values: `setting_name`

### 10. Cross-References

Link to other sections within the document:
```markdown
See [Section Name](#section-name) for more details
```

Link to other documentation files:
```markdown
See [API.md](API.md) for complete API documentation
```

## Writing Style

### Tone
- Professional and technical
- Clear and concise
- Avoid jargon when possible, or explain it when used
- Use active voice

### Formatting
- Use bold text (`**text**`) for emphasis
- Use italic text (`*text*`) for variables or placeholders
- Use code backticks for technical terms
- Use consistent capitalization (Title Case for headers, sentence case for descriptions)

### Length
- Keep sections focused on a single topic
- Break long sections into subsections
- Use bullet points for lists of more than 3 items
- Aim for clarity over brevity

## AI Agent Guidelines

When AI agents create documentation following this structure:

1. **Analyze the subject**: Understand what needs to be documented
2. **Follow the hierarchy**: Use proper heading levels (H1 → H2 → H3)
3. **Include examples**: Provide realistic code/data examples
4. **Be comprehensive**: Cover all important aspects without being verbose
5. **Maintain consistency**: Use the same formatting throughout
6. **Test examples**: Ensure code examples are syntactically correct
7. **Link related topics**: Use cross-references where appropriate

### Agent Checklist

- [ ] Document has clear title and overview
- [ ] Sections are properly organized with correct heading levels
- [ ] Code examples use proper language specification
- [ ] API endpoints follow the standard structure
- [ ] Data models include field descriptions and examples
- [ ] Important information is highlighted with notes/warnings
- [ ] Cross-references are used where appropriate
- [ ] Writing style is consistent throughout
- [ ] Technical terms are explained or used in context
- [ ] Document is comprehensive but not verbose

## File Template

```markdown
# [Document Title]

## Overview
[Brief description of document purpose]

## Section 1
[Content]

## Section 2
[Content]

### Subsection
[Content]

## Examples

### Example 1
```language
[code]
```

## Notes
> **Note:** [Important information]

## Related Documentation
- [Related Doc 1](path/to/doc1.md)
- [Related Doc 2](path/to/doc2.md)
```

## Version Control

- Include creation date in document metadata if needed
- Use git commits to track changes
- For major updates, add a "Changelog" section at the end

## Accessibility

- Use descriptive link text (avoid "click here")
- Provide alt text for images (if used)
- Ensure code examples are readable
- Use proper heading structure for screen readers
