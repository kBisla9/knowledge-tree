# REST API Conventions

## URL Structure

- Use plural nouns for resources: `/users`, `/orders`, `/products`
- Nest sub-resources: `/users/123/orders`
- Use kebab-case: `/order-items`, not `/orderItems`
- Max nesting depth: 2 levels

## HTTP Methods

| Method   | Purpose               | Idempotent | Example                |
|----------|-----------------------|------------|------------------------|
| `GET`    | Read resource(s)      | Yes        | `GET /users/123`       |
| `POST`   | Create resource       | No         | `POST /users`          |
| `PUT`    | Full replace          | Yes        | `PUT /users/123`       |
| `PATCH`  | Partial update        | Yes        | `PATCH /users/123`     |
| `DELETE` | Remove resource       | Yes        | `DELETE /users/123`    |

## Response Codes

- `200` — Success (GET, PUT, PATCH)
- `201` — Created (POST)
- `204` — No Content (DELETE)
- `400` — Client error (bad input)
- `401` — Unauthorized (no/invalid auth)
- `403` — Forbidden (valid auth, no permission)
- `404` — Not found
- `409` — Conflict (duplicate, version mismatch)
- `422` — Validation error
- `500` — Server error (never intentional)

## Pagination

Use cursor-based pagination for large datasets:

```json
{
  "data": [...],
  "next_cursor": "eyJpZCI6MTAwfQ==",
  "has_more": true
}
```

Offset-based is acceptable for small, stable datasets.

## Error Response Format

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Email is required",
    "details": [
      {"field": "email", "issue": "required"}
    ]
  }
}
```
