# Authentication Patterns

## Token Strategy: JWT + Refresh Tokens

- **Access token**: short-lived (15 minutes), stateless JWT
- **Refresh token**: long-lived (7 days), stored server-side, rotated on use

## JWT Claims

```json
{
  "sub": "user-uuid",
  "iat": 1700000000,
  "exp": 1700000900,
  "roles": ["user"],
  "org_id": "org-uuid"
}
```

Keep claims minimal. Don't store PII in tokens.

## Auth Flow

1. Client sends credentials to `POST /auth/login`
2. Server returns `{ access_token, refresh_token }`
3. Client sends `Authorization: Bearer <access_token>` on each request
4. On 401, client calls `POST /auth/refresh` with refresh token
5. Server rotates refresh token and issues new access token

## API Key Authentication

For service-to-service and third-party integrations:

- Prefix keys for identification: `kt_live_`, `kt_test_`
- Hash keys before storage (SHA-256)
- Support key rotation: allow multiple active keys per client
- Include key ID in header: `X-API-Key: kt_live_abc123`

## Security Checklist

- [ ] Passwords hashed with bcrypt (cost factor >= 12)
- [ ] Rate limit login attempts (5/minute per IP)
- [ ] HTTPS only — reject HTTP
- [ ] CORS configured for known origins only
- [ ] Refresh tokens invalidated on password change
- [ ] Tokens never logged or stored in URLs
