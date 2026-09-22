---
id: [entity-id]
type: [person|project|library|concept|file|decision|pattern|tool]
name: [Entity Name]
status: [active|stale|superseded|archived]
confidence: 0.0
sources: []
created_at: [YYYY-MM-DD]          # compile creation date — set automatically by compile
published_at: ""                 # source content's own publication date (YYYY-MM-DD); omit if none
# For time-sensitive rules only; dates are applicability, never publication/compile time:
# effective_from: YYYY-MM-DD      # inclusive
# effective_until: YYYY-MM-DD     # exclusive
# supersedes: [/entities/old-rule.md]
# superseded_by: [/entities/new-rule.md]
# jurisdiction: [region or legal scope]
# audience: [people or systems this applies to]
# document_status: [official|approved|draft|meeting-note]
# source_authority: 0.0          # only when source authority is known; never guess
# claims:                        # atomic, source-grounded facts (OKF extension)
#   - subject: [who/what]
#     predicate: [property/rule]
#     value: [exact source value]
#     modality: [fact|must|must_not|may|should|entitlement|definition|procedure]
#     conditions: []
#     exceptions: []
#     source: {section: "...", page: 1}
# visuals:                       # required for every retained information-bearing figure
#   - id: approval-swimlane-p12
#     kind: swimlane
#     title: 订单审批泳道图
#     image: ../assets/source/page-012.png
#     source_locator: Page 12
#     summary: 申请人提交后由主管审批，超额订单转财务复核。
#     keywords: [订单审批, 主管, 财务复核]
#     entities: [申请人, 主管, 财务]
#     lanes: [申请人, 主管, 财务]
#     nodes: []
#     edges: []
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

## Key Facts

| Attribute | Value |
|---|---|
| [queryable fact] | [exact source value, including units and footnotes] |

## Details

<!-- Fill in relevant sections based on entity type. Delete unused sections. -->

## Visual Evidence

<!-- For every `visuals` record, embed the exact original image and explain the
     visually encoded relationships, direction, ownership, scale, values, and
     uncertainty. Delete this section only when the source has no useful figure. -->

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
