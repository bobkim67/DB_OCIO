# CLAUDE.md - AI Assistant Guide for DB_OCIO

Last Updated: 2026-01-23

## Repository Overview

**Repository Name**: DB_OCIO
**Purpose**: Database and OCIO (Office of the Chief Information Officer) related project
**Current State**: Initial repository setup

This document serves as a comprehensive guide for AI assistants working on this codebase. It outlines the repository structure, development workflows, coding conventions, and best practices.

---

## Table of Contents

1. [Repository Structure](#repository-structure)
2. [Technology Stack](#technology-stack)
3. [Development Workflow](#development-workflow)
4. [Coding Conventions](#coding-conventions)
5. [Git Practices](#git-practices)
6. [Database Guidelines](#database-guidelines)
7. [Security Considerations](#security-considerations)
8. [Testing Strategy](#testing-strategy)
9. [Documentation Standards](#documentation-standards)
10. [Common Tasks](#common-tasks)

---

## Repository Structure

As the repository develops, maintain this directory structure:

```
DB_OCIO/
├── src/                    # Source code
│   ├── models/            # Database models/schemas
│   ├── controllers/       # Business logic controllers
│   ├── services/          # Service layer
│   ├── routes/            # API routes/endpoints
│   ├── utils/             # Utility functions
│   └── config/            # Configuration files
├── tests/                 # Test files
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── fixtures/         # Test data
├── migrations/            # Database migrations
├── scripts/              # Utility scripts
├── docs/                 # Documentation
├── .env.example          # Environment variables template
├── .gitignore           # Git ignore rules
├── README.md            # Project documentation
└── CLAUDE.md            # This file
```

### Key Directories

- **src/models**: Database schema definitions and ORM models
- **src/controllers**: Request handlers and business logic
- **src/services**: Reusable business logic services
- **migrations**: Version-controlled database schema changes
- **tests**: Comprehensive test coverage for all components

---

## Technology Stack

Document the stack as it's established. Common patterns for DB projects:

### Expected Technologies
- **Database**: PostgreSQL, MySQL, MongoDB, or similar
- **Backend Framework**: Node.js (Express), Python (FastAPI/Django), or similar
- **ORM/ODM**: Sequelize, TypeORM, SQLAlchemy, Mongoose, or similar
- **Testing**: Jest, Pytest, Mocha, or similar
- **Version Control**: Git

### Dependencies Management
- Keep dependencies up to date
- Document all major dependencies in README.md
- Use lock files (package-lock.json, poetry.lock, etc.)
- Regular security audits with `npm audit` or equivalent

---

## Development Workflow

### Branch Strategy

1. **Main Branch**: `main` or `master` - production-ready code
2. **Development Branch**: `develop` - integration branch
3. **Feature Branches**: `claude/feature-name-{session-id}` - individual features
4. **Hotfix Branches**: `hotfix/description` - critical production fixes

### Standard Development Flow

1. **Start New Feature**:
   ```bash
   git checkout -b claude/feature-name-{session-id}
   ```

2. **Make Changes**: Follow coding conventions below

3. **Test Locally**: Run all tests before committing

4. **Commit Changes**:
   ```bash
   git add [specific-files]
   git commit -m "feat: descriptive message

   https://claude.ai/code/session_[session-id]"
   ```

5. **Push to Remote**:
   ```bash
   git push -u origin claude/feature-name-{session-id}
   ```

6. **Create Pull Request**: Use GitHub CLI or web interface

---

## Coding Conventions

### General Principles

1. **Keep It Simple**: Avoid over-engineering solutions
2. **DRY Principle**: Don't Repeat Yourself - extract common logic
3. **SOLID Principles**: Follow object-oriented design principles
4. **Security First**: Never commit secrets, validate all inputs
5. **Error Handling**: Implement comprehensive error handling

### Code Style

- **Naming Conventions**:
  - Variables/Functions: `camelCase` or `snake_case` (be consistent)
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`
  - Files: `kebab-case` or `snake_case`

- **File Organization**:
  - One class/model per file
  - Group related functionality
  - Keep files under 300 lines when possible

- **Comments**:
  - Document WHY, not WHAT
  - Use JSDoc/docstrings for public APIs
  - Avoid obvious comments

### Database-Specific Conventions

1. **Naming**:
   - Tables: `plural_snake_case` (e.g., `users`, `order_items`)
   - Columns: `snake_case`
   - Indexes: `idx_table_column`
   - Foreign Keys: `fk_table_reference`

2. **Migrations**:
   - Always reversible (include up/down methods)
   - Descriptive names with timestamps
   - Test migrations before committing

3. **Queries**:
   - Use parameterized queries (prevent SQL injection)
   - Index frequently queried columns
   - Avoid N+1 queries
   - Use connection pooling

---

## Git Practices

### Commit Message Format

Use conventional commits:

```
<type>: <subject>

<body>

https://claude.ai/code/session_[session-id]
```

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `test`: Test additions/changes
- `chore`: Maintenance tasks
- `perf`: Performance improvements

**Examples**:
```
feat: add user authentication endpoint

Implements JWT-based authentication with refresh tokens

https://claude.ai/code/session_abc123
```

### Branch Protection

- Never force push to main/develop
- Require pull request reviews
- Run CI/CD checks before merging
- Delete feature branches after merging

### Pre-commit Checks

Before committing:
1. Run linter
2. Run tests
3. Check for secrets/credentials
4. Verify no debug code

---

## Database Guidelines

### Schema Design

1. **Normalization**: Follow 3NF unless denormalization is justified
2. **Data Types**: Use appropriate types (avoid VARCHAR(255) default)
3. **Constraints**: Use NOT NULL, UNIQUE, CHECK where appropriate
4. **Indexes**: Index foreign keys and frequently queried columns
5. **Timestamps**: Include `created_at` and `updated_at` columns

### Migration Best Practices

```sql
-- Always include rollback capability
-- Example migration structure:

-- UP Migration
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);

-- DOWN Migration (rollback)
DROP INDEX IF EXISTS idx_users_email;
DROP TABLE IF EXISTS users;
```

### Performance Optimization

1. **Query Optimization**:
   - Use EXPLAIN to analyze queries
   - Avoid SELECT *
   - Limit result sets
   - Use appropriate JOIN types

2. **Connection Management**:
   - Use connection pooling
   - Close connections properly
   - Set appropriate timeout values

3. **Caching**:
   - Cache frequently accessed data
   - Implement cache invalidation strategy
   - Use Redis or similar for distributed caching

---

## Security Considerations

### Critical Security Rules

1. **Never Commit Secrets**:
   - Use environment variables
   - Add `.env` to `.gitignore`
   - Use `.env.example` as template
   - Use secret management tools for production

2. **Input Validation**:
   - Validate all user inputs
   - Sanitize data before database operations
   - Use parameterized queries (prevent SQL injection)
   - Implement rate limiting

3. **Authentication & Authorization**:
   - Use strong password hashing (bcrypt, argon2)
   - Implement proper session management
   - Use HTTPS in production
   - Follow principle of least privilege

4. **Data Protection**:
   - Encrypt sensitive data at rest
   - Use encrypted connections (TLS/SSL)
   - Implement proper backup strategies
   - Follow GDPR/compliance requirements

### Common Vulnerabilities to Avoid

- SQL Injection: Use parameterized queries
- XSS: Sanitize outputs
- CSRF: Use tokens
- Authentication bypass: Proper session validation
- Insecure dependencies: Regular security audits

---

## Testing Strategy

### Test Coverage Goals

- Unit Tests: 80%+ coverage
- Integration Tests: Critical paths
- End-to-End Tests: User workflows

### Test Structure

```javascript
// Example test structure
describe('UserService', () => {
    describe('createUser', () => {
        it('should create user with valid data', async () => {
            // Arrange
            const userData = { email: 'test@example.com', password: 'secure123' };

            // Act
            const user = await UserService.createUser(userData);

            // Assert
            expect(user).toHaveProperty('id');
            expect(user.email).toBe(userData.email);
        });

        it('should reject duplicate email', async () => {
            // Test implementation
        });
    });
});
```

### Testing Best Practices

1. **Test Isolation**: Each test should be independent
2. **Use Fixtures**: Reusable test data
3. **Mock External Services**: Don't rely on external APIs
4. **Database Tests**: Use test database or in-memory DB
5. **Continuous Integration**: Run tests on every commit

---

## Documentation Standards

### Code Documentation

1. **README.md** must include:
   - Project description
   - Installation instructions
   - Configuration guide
   - Usage examples
   - Contributing guidelines

2. **API Documentation**:
   - Document all endpoints
   - Include request/response examples
   - Specify authentication requirements
   - Use tools like Swagger/OpenAPI

3. **Inline Documentation**:
   - Document complex logic
   - Explain non-obvious decisions
   - Keep comments up to date

### Database Documentation

- Maintain ER diagrams
- Document table purposes
- Explain complex relationships
- Keep migration history clear

---

## Common Tasks

### Adding a New Feature

1. Create feature branch from develop
2. Implement feature following conventions
3. Write tests (TDD preferred)
4. Update documentation
5. Create pull request
6. Address review comments
7. Merge after approval

### Database Changes

1. Create migration file
2. Test migration locally
3. Include rollback logic
4. Update models/schemas
5. Update documentation
6. Test with production-like data

### Bug Fixes

1. Reproduce the bug
2. Write failing test
3. Implement fix
4. Verify test passes
5. Check for similar issues
6. Document fix in commit

### Code Review Checklist

- [ ] Code follows conventions
- [ ] Tests are included and passing
- [ ] Documentation is updated
- [ ] No security vulnerabilities
- [ ] No hardcoded credentials
- [ ] Error handling is comprehensive
- [ ] Performance is acceptable
- [ ] Database migrations are reversible

---

## AI Assistant Specific Guidelines

### When Working on This Codebase

1. **Always Read First**: Never propose changes without reading existing code
2. **Use TodoWrite**: Track multi-step tasks with the TodoWrite tool
3. **Security Priority**: Flag any security concerns immediately
4. **Ask When Uncertain**: Clarify requirements before implementing
5. **Minimal Changes**: Only change what's necessary for the task
6. **Test Before Commit**: Verify changes work as expected

### Tool Usage Preferences

- **File Search**: Use Task tool with Explore agent for codebase exploration
- **File Operations**: Use Read/Edit/Write tools, not bash commands
- **Parallel Operations**: Run independent tasks concurrently
- **Git Operations**: Follow retry logic for network operations

### Commit Workflow

1. Read relevant files first
2. Check git status for staged/unstaged changes
3. Review git log for commit message style
4. Stage specific files (avoid `git add -A`)
5. Create commit with session URL
6. Verify with git status

### Pull Request Creation

1. Check branch status and diff
2. Review ALL commits in the branch
3. Write comprehensive PR description
4. Include test plan
5. Push and create PR with gh CLI

---

## Getting Started

### Initial Setup (To Be Updated)

When the project structure is established, document:

1. Prerequisites (Node.js, Python, database, etc.)
2. Installation steps
3. Environment configuration
4. Database setup
5. Running the application
6. Running tests

### Environment Variables Template

Create `.env.example`:

```bash
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=db_ocio
DB_USER=your_username
DB_PASSWORD=your_password

# Application Configuration
NODE_ENV=development
PORT=3000

# Security
JWT_SECRET=your_jwt_secret
ENCRYPTION_KEY=your_encryption_key

# External Services
API_KEY=your_api_key
```

---

## Maintenance and Updates

### Regular Tasks

- Update dependencies monthly
- Run security audits weekly
- Review and close stale issues
- Update documentation with code changes
- Optimize slow queries
- Monitor database performance

### This Document

- Update when project structure changes
- Add new conventions as established
- Document technology stack decisions
- Keep examples current with codebase

---

## Resources and References

### Documentation Links
- [PostgreSQL Best Practices](https://wiki.postgresql.org/wiki/Don%27t_Do_This)
- [SQL Style Guide](https://www.sqlstyle.guide/)
- [Git Conventional Commits](https://www.conventionalcommits.org/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)

### Tools and Utilities
- Database migration tools
- Linting and formatting
- Testing frameworks
- CI/CD platforms

---

## Contact and Support

Document team contacts, communication channels, and support resources as they're established.

---

**Note**: This document is a living guide and should be updated as the project evolves. All contributors should familiarize themselves with these guidelines before making changes.
