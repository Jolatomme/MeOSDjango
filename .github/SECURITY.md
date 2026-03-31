# Security Policy

## Reporting a Vulnerability

We take the security of MeOSDjango seriously. If you discover a security vulnerability, please report it responsibly by emailing instead of using the public issue tracker.

**Do not open a public GitHub issue for security vulnerabilities.**

### How to Report

1. **Email** your vulnerability report to: security@example.com
2. **Include the following details:**
   - Description of the vulnerability
   - Steps to reproduce (if applicable)
   - Potential impact
   - Affected versions
   - Any suggested fixes (optional)

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
- **Investigation**: Our team will investigate and determine the severity
- **Timeline**: We aim to publish a fix within 90 days
- **Disclosure**: We will credit you (if you wish) when we publish the security advisory

---

## Supported Versions

We provide security updates for the following versions:

| Version | Supported          | End of Support |
|---------|-------------------|-----------------|
| 1.x     | ✅ Yes            | 2027-12-31    |
| 0.x     | ⚠️ Limited Support | 2026-06-30    |

**Note**: Users are strongly encouraged to upgrade to the latest version.

---

## Security Best Practices for Contributors

When contributing to MeOSDjango, please follow these guidelines:

### Code Security
- ✅ **Never commit secrets** (API keys, passwords, tokens)
- ✅ **Use environment variables** for sensitive configuration
- ✅ **Validate user input** to prevent injection attacks
- ✅ **Use Django's built-in security features** (CSRF protection, SQL parameterization)
- ✅ **Keep dependencies updated** and monitor for vulnerabilities

### Dependency Management
- Run `pip-audit` or `safety` to check for vulnerable dependencies
- Keep Django and all packages up to date
- Review security advisories regularly

### Data Protection
- Ensure user data is properly validated and sanitized
- Use Django's ORM to prevent SQL injection
- Apply proper authentication and authorization checks
- Encrypt sensitive data at rest and in transit

---

## Known Issues and Vulnerabilities

We maintain a public advisory list at [GitHub Security Advisories](https://github.com/Jolatomme/MeOSDjango/security/advisories).

---

## Security Headers and Configuration

MeOSDjango should be deployed with:
- HTTPS/TLS enabled (enforce with `SECURE_SSL_REDIRECT = True`)
- Security headers configured (`SECURE_HSTS_SECONDS`, `SECURE_CONTENT_SECURITY_POLICY`)
- Debug mode disabled in production (`DEBUG = False`)
- `ALLOWED_HOSTS` properly configured

---

## Dependencies and Third-Party Libraries

We regularly audit our dependencies for security vulnerabilities using:
- GitHub's Dependabot
- `pip-audit`
- Regular security updates

If you discover a vulnerability in a dependency, please report it to the maintainers of that library and notify us.

---

## Questions?

If you have questions about our security practices, please reach out to **security@example.com**.

---

## Attribution

This security policy is based on [GitHub's Security Policy best practices](https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository).
