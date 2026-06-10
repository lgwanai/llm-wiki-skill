# SOC 2 Type II Compliance

## Certification Status
- **Certification**: SOC 2 Type II
- **Audit Period**: 2025-01 to 2025-12
- **Auditor**: Schellman & Company
- **Trust Services Criteria**: Security, Availability, Confidentiality

## Evidence Retention Policy

SOC 2 requires organizations to retain audit evidence for a defined period. Per our compliance policy (`policy-handbook.md#S3`):

| Evidence Type | Retention Period | Storage Location |
|--------------|-----------------|------------------|
| Access logs | 365 days | S3: compliance-logs/access/ |
| Change management records | 730 days (2 years) | S3: compliance-logs/change/ |
| Incident response reports | 2555 days (7 years) | S3: compliance-reports/incidents/ |
| Backup verification logs | 365 days | S3: compliance-logs/backup/ |
| User access reviews | 730 days (2 years) | S3: compliance-reports/access-review/ |
| Vulnerability scan reports | 1095 days (3 years) | S3: compliance-reports/vulnerability/ |

The evidence retention rule is established in `policy-handbook.md#S3` and enforced through automated lifecycle policies on S3 buckets.

## Key Controls

### Access Control
- All production access requires MFA (multi-factor authentication)
- Access reviews conducted quarterly by department heads
- Privileged access requires temporary elevation with JIT (just-in-time) approval
- All access changes logged to immutable audit trail

### Change Management
- All production changes require peer review + automated testing
- Database schema changes require DBA approval
- Emergency changes require post-hoc review within 24 hours
- Change success rate monitored monthly (target > 95%)

### Monitoring & Alerting
- All security events logged centrally (SIEM)
- Critical alerts must be acknowledged within 15 minutes
- Incident response triggered for P0/P1 security events
- Quarterly penetration testing by external firm

## Audit Evidence Collection

### Automated Collection
All evidence is collected automatically through:
- AWS CloudTrail for API activity
- GitHub audit logs for code changes
- PagerDuty for incident response metrics
- Okta for access management logs
- Datadog for infrastructure monitoring

### Manual Collection
- Quarterly access review sign-offs (PDF)
- Annual risk assessment documentation
- Vendor security assessments
- Tabletop exercise results

## Recent Findings

### 2025 Audit (Clean Opinion)
No exceptions noted. Areas of commendation:
- Automated evidence collection pipeline
- JIT access system design
- Incident response time (avg 8 min for P1)

### Prior Year (2024)
Two minor findings (both remediated):
1. Access review for 3 contractors was 5 days late → Automated reminders implemented
2. One database backup verification failed without alert → Backup monitoring added

## Point of Contact
- Compliance Officer: compliance@company.com
- Security Team: security@company.com
- Evidence Requests: Submit via Jira "Compliance" project with "SOC2-Evidence" component
