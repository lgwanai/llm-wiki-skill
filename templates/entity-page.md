---
id: [entity-id]
type: [person|project|library|concept|file|decision|pattern|tool]
name: [Entity Name]
status: [active|stale|superseded|archived]
confidence: 0.0
sources: []
last_confirmed: [YYYY-MM-DD]
reinforcements: 0
contradictions: []
quality_score: 0.0
tags: []
scope: [private|team|public]
owner: [agent-id or username]
---

# [Entity Name]

## Overview

[A concise description of what this entity is and why it matters. 2-4 sentences.]

## Details

<!-- Fill in relevant sections based on entity type. Delete unused sections. -->

### For `person` entities
- **Role**: [Their role in the project]
- **Team**: [Team/department]
- **Expertise**: [Areas of expertise]
- **Contact**: [Preferred contact method, if appropriate for scope]
- **Preferences**: [Notable preferences or working style]

### For `project` entities
- **Repository**: [GitHub/GitLab URL or local path]
- **Language(s)**: [Primary programming languages]
- **Status**: [Active, maintenance, deprecated, planned]
- **Owner**: [[person-entity]]
- **Dependencies**: [[library-entity]], [[project-entity]]

### For `library` entities
- **Version**: [Current version]
- **Purpose**: [What it's used for]
- **Documentation**: [URL to official docs]
- **Used by**: [[project-entity]], [[project-entity]]
- **Alternatives considered**: [[library-entity]]
- **License**: [License type]

### For `concept` entities
- **Domain**: [Architecture, distributed systems, databases, etc.]
- **Definition**: [Clear definition]
- **Related concepts**: [[concept-entity]], [[concept-entity]]
- **Examples in codebase**: [[file-entity]], [[project-entity]]

### For `file` entities
- **Path**: [Relative path from project root]
- **Purpose**: [What this file does]
- **Language**: [Programming language]
- **Last modified**: [Date]

### For `pattern` entities
- **Category**: [Design pattern, coding convention, workflow, deployment]
- **Frequency**: [How often observed: once, occasionally, frequently, always]
- **Examples**: [[file-entity]], [[project-entity]]

## Relationships

<!-- List incoming and outgoing edges with their types -->

### This entity...
- *[relationship-type]* [[target-entity]] — [brief description]

### Referenced by
<!-- Auto-generated during lint, or add manually -->
- [[source-entity]] — *[relationship-type]* — [brief description]

## History

<!-- Significant events related to this entity, most recent first -->
- **[YYYY-MM-DD]**: [What happened]
- **[YYYY-MM-DD]**: [What happened]

## Notes

<!-- Additional context, caveats, or open questions -->
