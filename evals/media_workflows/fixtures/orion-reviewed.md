# Orion Service Review

Visual observations from the supplied Orion JPG. The directed edges below follow the arrowheads in the original. The schedule uses the labeled weekly windows. The chart values are printed labels.

## Page 1

### Incident workflow

- Alert → Triage
- Triage → Critical?
- Critical? → Page SRE [Yes]
- Critical? → Ticket [No]
- Page SRE → Mitigate
- Mitigate → Close
- Ticket → Close

### System architecture

- Portal → Gateway
- Gateway → Router
- Router → Cache
- Router → Queue
- Queue → Worker
- Worker → Vault

### Reporting lines

- Maya → Iris
- Maya → Noah
- Iris → SRE
- Iris → QA
- Noah → Data

### SLA

| Tier | Minutes | Owner |
| --- | --- | --- |
| P1 | 15 | Iris |
| P2 | 45 | Noah |
| P3 | 120 | Maya |

### Gantt

| Task | Start | End |
| --- | --- | --- |
| Design | W1 | W2 |
| Build | W2 | W3 |
| Launch | W4 | W4 |

### Release readiness

- Readiness → Security
- Readiness → Reliability
- Security → Review
- Reliability → Rollback

### Tickets by month

| Month | Tickets |
| --- | --- |
| Jan | 40 |
| Feb | 60 |
| Mar | 100 |

### Workload split

| Team | Share |
| --- | --- |
| Ops | 50% |
| Data | 30% |
| QA | 20% |
