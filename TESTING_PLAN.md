# Aider Extension Testing Plan

## How Each Feature Maps to Real Development Workflows

---

## 1. Multi-Agent System (`aider/agents/`)

### Workflow: Comprehensive Code Review
```
Developer finishes feature → Needs review:
  ├─ Spawn Security Agent → Checks for SQL injection, XSS, secrets
  ├─ Spawn Performance Agent → Analyzes algorithmic complexity
  ├─ Spawn Style Agent → Enforces PEP8, type hints
  ├─ Spawn Test Coverage Agent → Identifies untested paths
  └─ Results merged into single actionable report

Test: test_spawn_multiple_agents() validates this workflow
```

### Workflow: Parallel Bug Investigation
```
Critical production bug reported:
  ├─ Agent 1 → Analyze error logs and stack traces
  ├─ Agent 2 → Check recent commits for culprits  
  ├─ Agent 3 → Search codebase for similar patterns
  └─ Agent 4 → Verify reproduction steps

Results combined → Root cause identified 5x faster
```

### Workflow: Architecture Review
```
Senior dev needs to review complex refactoring:
  ├─ 3 agents analyze different layers (API, DB, Frontend)
  ├─ Each focuses on interface contracts
  └─ Aggregated findings highlight breaking changes
```

---

## 2. Skills System (`aider/skills/`)

### Workflow: Security Audit
```
Before release, run: /skill run security-audit
  → Scans for hardcoded credentials
  → Checks input validation gaps
  → Identifies timing attack vulnerabilities
  → Validates authentication flows
  → Generates remediation checklist

Test: Found real issues in test_repo (auth.py credentials)
```

### Workflow: Test Generation
```
New module created → Need tests:
  /skill run test-generation --target src/payments/
  → Analyzes public interfaces
  → Generates pytest unit tests
  → Creates edge case scenarios
  → Adds integration test stubs
  → Reports coverage gaps
```

### Workflow: Refactoring
```
Legacy code needs modernization:
  /skill run refactoring --pattern "convert to dataclasses"
  → Identifies candidate classes
  → Generates transformed code
  → Preserves serialization behavior
  → Updates type annotations
  → Validates no logic changes
```

### Workflow: Documentation
```
Code written, docs missing:
  /skill run documentation --generate-api-docs
  → Scans public APIs
  → Generates docstrings from types
  → Creates README examples
  → Validates code/doc consistency
```

### Workflow: Performance Review
```
Before optimization:
  /skill run performance-review --profile
  → Identifies N+1 queries
  → Finds unnecessary allocations
  → Detects blocking I/O in async code
  → Suggests algorithm improvements
```

---

## 3. ACP - Agent Client Protocol (`aider/editor_protocol/`)

### Workflow: IDE-Assisted Refactoring
```
In VS Code:
  1. Select function → Right-click "Refactor with Aider"
  2. Type: "Extract this into a class"
  3. ACP streams changes in diff view
  4. Review → Accept → Code updated inline
  5. Follow-up: "Add unit tests for this class"
  6. Tests generated and placed in test file
```

### Workflow: Interactive Debugging
```
Developer debugging complex issue:
  1. Set breakpoint → Inspect variables
  2. Copy stack trace → Send via ACP
  3. "Explain why this null pointer occurs"
  4. Aider analyzes call chain
  5. "Suggest fix and apply"
  6. Fix applied, tests run automatically
```

### Workflow: Learning Codebase
```
New team member onboarding:
  1. Open unfamiliar module
  2. "Explain how authentication flows through this"
  3. ACP provides step-by-step walkthrough
  4. "Show me where user roles are checked"
  5. Navigates to relevant files
  6. Context preserved across questions
```

---

## 4. A2A - Agent-to-Agent Protocol (`aider/a2a/`)

### Workflow: Distributed Feature Development
```
Building new payment feature:
  ├─ Payment Agent handles core logic
  ├─ Fraud Detection Agent validates risks
  ├─ Compliance Agent checks regulations
  └─ Agents negotiate via A2A → Unified implementation
```

### Workflow: Multi-Stage Pipeline
```
CI-like workflow within Aider:
  Stage 1: Code Generation Agent writes feature
  Stage 2: Review Agent validates quality
  Stage 3: Test Agent generates coverage
  Stage 4: Security Agent scans for issues
  A2A coordinates handoffs between stages
```

---

## 5. Hooks System (`aider/hooks*.py`)

### Workflow: Pre-Commit Validation
```
Developer: /commit "Add user login"
  → PRE_COMMIT hook fires:
      1. Run flake8 → Fails on style issues
      2. Run mypy → Type check errors
      3. Run security scan → Block secrets
  → If any fail: Commit blocked with errors
  → If all pass: Commit proceeds
  → POST_COMMIT: Notify team Slack
```

### Workflow: Automated Testing on Edit
```
Aider suggests fix for bug:
  → PRE_EDIT: Run affected unit tests (verify current failure)
  → EDIT: Apply fix
  → POST_EDIT: Re-run tests (verify fix works)
  → If tests fail: Auto-revert with warning
```

### Workflow: Documentation Sync
```
API contract changed:
  → POST_EDIT hook:
      1. Detect public interface change
      2. Regenerate OpenAPI spec
      3. Update API documentation
      4. Notify API consumers
```

### Workflow: Deployment Pipeline
```
Release commit made:
  → POST_COMMIT:
      1. Tag version
      2. Build Docker image
      3. Deploy to staging
      4. Run smoke tests
      5. Notify on success/failure
```

---

## 6. Tools v2 System (`aider/tools_v2/`)

### Workflow: Safe Script Execution
```
Aider needs to analyze production logs:
  → Suggests Python script
  → Runs in sandbox (firejail):
      - No network access
      - Read-only filesystem except /tmp
      - 30 second timeout
      - Memory limits enforced
  → If script crashes: Isolated, main process safe
  → If output large: Smart compression applied
```

### Workflow: Database Migration Safety
```
Aider generates migration:
  → Runs in sandbox with:
      - Database credentials from env only
      - Dry-run mode enforced
      - Transaction rollback on error
      - Execution time limit
  → Validates SQL before applying
  → Cost tracked for budget awareness
```

---

## 7. MCP - Model Context Protocol (`aider/mcp/`)

### Workflow: External Tool Integration
```
Claude Desktop + Aider MCP:
  User: "Find all unused functions"
  Claude → Calls aider/analyze_code tool
  Aider → Runs static analysis
  Result → Returns function list with locations
  Claude → "Remove them"
  Aider → Applies deletions, runs tests
```

---

## 8. OpenClaw Gateway Integration

### Workflow: On-Premise Security Review
```
Banking client, sensitive codebase:
  → Aider connects to local OpenClaw (air-gapped)
  → Llama 70B runs on internal GPU cluster
  → /skill run security-audit:
      - No code leaves premises
      - No API keys to external services
      - Full audit trail locally
  → Falls back to cloud only if explicitly allowed
```

---

## End-to-End Workflow Tests

### Test 1: Feature Development Lifecycle
```
Scenario: Implement user authentication system

Step 1 - Architecture (Swarm Mode):
  /swarm create "Build auth system with JWT tokens"
  → Creates: interfaces.py, services.py, repositories.py

Step 2 - Security Audit:
  /skill run security-audit --target auth/
  → Finds: Hardcoded secret key
  → Suggests: Use environment variables

Step 3 - Parallel Review:
  /agent spawn 3 --task "Review auth implementation"
  → Agent 1: Check token expiration logic
  → Agent 2: Verify password hashing
  → Agent 3: Validate middleware integration

Step 4 - Test Generation:
  /skill run test-generation
  → Unit tests for login/logout
  → Integration tests for token refresh
  → Edge case: expired token handling

Step 5 - Implementation:
  Aider fixes found issues
  → Moves secret to env var
  → Adds token rotation
  → Implements rate limiting

Step 6 - Pre-commit Validation:
  /commit "Add JWT authentication with tests"
  → Hooks run: lint, type-check, security scan
  → All pass → Committed
  → Post-commit: Deploys to staging

Validation: All components work together
```

### Test 2: Bug Fix Workflow
```
Scenario: Production race condition reported

Step 1 - Investigation:
  /agent spawn 4 --task "Analyze race condition in order.py"
  → Agent 1: Analyze concurrent access patterns
  → Agent 2: Review database transaction isolation
  → Agent 3: Check locking mechanisms
  → Agent 4: Search for similar bugs in history

Step 2 - Root Cause:
  Aggregated findings → Missing row-level lock

Step 3 - Fix:
  ACP inline: "Add SELECT FOR UPDATE"
  → Streams change in diff view
  → Developer accepts

Step 4 - Validation:
  PRE_EDIT hook: Run failing test case
  POST_EDIT hook: Verify test passes

Step 5 - Regression Prevention:
  /skill run test-generation --focus concurrency
  → Adds stress tests for concurrent orders

Step 6 - Commit:
  /commit "Fix race condition in order processing"
  → Security scan: Pass
  → Performance check: No degradation
  → Documentation hook: Updates changelog
```

### Test 3: Refactoring at Scale
```
Scenario: Migrate from Flask to FastAPI

Step 1 - Analysis:
  /skill run refactoring --analyze "flask-to-fastapi"
  → Identifies: 47 route handlers
  → Dependencies: flask-sqlalchemy → sqlalchemy
  → Breaking: Session management changes

Step 2 - Swarm Planning:
  /swarm split --strategy "by-module"
  → Creates migration plan per module
  → Identifies test updates needed

Step 3 - Parallel Execution:
  /agent spawn 5 --task "Migrate routes group 1"
  → Each agent handles ~9 routes
  → A2A coordinates shared dependencies

Step 4 - Integration:
  → Agents report conflicts
  → Aider resolves manually
  → Integration tests run

Step 5 - Validation:
  /skill run security-audit (new framework patterns)
  /skill run performance-review (async benefits)

Step 6 - Documentation:
  /skill run documentation --migration-guide
  → Updates README
  → API docs regenerated
  → Developer docs updated
```

### Test 4: Security Response
```
Scenario: CVE disclosed in dependency

Step 1 - Immediate Assessment:
  /skill run security-audit --check-dependencies
  → Identifies: 3 affected packages
  → Severity: Critical in auth middleware

Step 2 - Fix Generation:
  /agent spawn 2:
  → Agent 1: Update requirements.txt with safe versions
  → Agent 2: Check for breaking changes in new versions

Step 3 - Validation:
  → Sandbox runs test suite with new deps
  → Circuit breaker if tests fail
  → Cost tracking for emergency response

Step 4 - Deployment:
  /commit "Security: Update dependencies for CVE-XXXX"
  → Pre-commit: Vulnerability scan
  → Post-commit: Emergency deploy pipeline
```

---

## Test Execution Summary

| Workflow | Features Tested | Test Command |
|----------|-----------------|--------------|
| Code Review | Agents, Skills | `pytest test_agents.py -k spawn` |
| Security Audit | Skills, Hooks | `/skill run security-audit` |
| Refactoring | ACP, Skills, Hooks | ACP inline + `/skill refactoring` |
| Feature Dev | All components | Full E2E test sequence |
| Bug Fix | Agents, ACP, Hooks | Investigation → Fix → Validation |
| Documentation | Skills, Hooks | `/skill run documentation` |

---

## Success Criteria

For each workflow, verify:
1. **Correctness**: Output matches expected results
2. **Performance**: Completes within timeout
3. **Safety**: Sandboxed, no data loss
4. **Integration**: Components work together
5. **Recovery**: Graceful degradation on failure
