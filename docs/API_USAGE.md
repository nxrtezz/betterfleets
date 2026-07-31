# API Key Authentication for Creating Operators

This document explains how to use API keys to create, update, or delete operators via the API.

**Note**: GET requests to list or retrieve operators do not require API key authentication. However, you can optionally include an API key with GET requests. When rate limiting is implemented, requests with valid API keys will bypass rate limits. API keys are required for write operations (POST, PUT, PATCH, DELETE).

## Setting Up API Keys

1. **Create an API Key** via the Django Admin:
   - Log in to the Django admin interface
   - Navigate to a User account
   - In the "API keys" section, click "Add another API Key"
   - Enter a name to identify the key (e.g., "Operator Import Script")
   - Save - the key will be automatically generated
   - Copy the key - you won't be able to see it again in full

2. **Alternatively, create via the API Key admin page**:
   - Navigate to Accounts > API Keys in the admin
   - Add a new API Key and associate it with a user

## Using the API

### Authentication

Include the API key in your request headers using either:
- `Authorization: Bearer YOUR_API_KEY`
- `Authorization: Key YOUR_API_KEY`
- `X-API-Key: YOUR_API_KEY`

### Creating an Operator

**Endpoint**: `POST /api/operators/`

**Example Request**:
```bash
curl -X POST https://your-domain.com/api/operators/ \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "noc": "TEST",
    "name": "Test Operator",
    "vehicle_mode": "bus",
    "url": "https://example.com"
  }'
```

**Required Fields**:
- `noc`: Operator code (primary key, max 10 characters)
- `name`: Operator name (max 100 characters)

**Optional Fields**:
- `vehicle_mode`: Mode of transport (e.g., "bus", "coach", "tram")
- `url`: Website URL
- `twitter`: Twitter handle
- `social_x`: X (Twitter) URL
- `social_fb`: Facebook URL
- `social_instagram`: Instagram URL
- `social_linkedin`: LinkedIn URL
- `social_youtube`: YouTube URL
- `social_tiktok`: TikTok URL
- `social_threads`: Threads URL
- `social_bluesky`: Bluesky URL
- `social_mastodon`: Mastodon URL
- `social_other`: Other social media URL
- `slogan`: Slogan
- `aka`: Also known as
- `preserved`: Boolean for preserved operators
- `ceased_operations_on`: Date when operations ceased
- `external_id`: External identifier
- `region_id`: Region ID

**Note**: The `slug` field is automatically generated and read-only.

### Listing Operators with Vehicle Count

When listing operators via GET requests, each operator includes a `vehicle_count` field showing the number of non-withdrawn vehicles.

**Endpoint**: `GET /api/operators/`

**Example Request**:
```bash
curl https://your-domain.com/api/operators/
```

**Example Response**:
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "noc": "TEST",
      "external_id": "",
      "slug": "test-operator",
      "name": "Test Operator",
      "slogan": "",
      "logo": null,
      "aka": "",
      "preserved": false,
      "ceased_operations_on": null,
      "vehicle_mode": "bus",
      "mode": "bus",
      "region_id": null,
      "url": "https://example.com",
      "twitter": "",
      "social_x": "",
      "social_fb": "",
      "social_instagram": "",
      "social_linkedin": "",
      "social_youtube": "",
      "social_tiktok": "",
      "social_threads": "",
      "social_bluesky": "",
      "social_mastodon": "",
      "social_other": "",
      "garages": [],
      "vehicle_count": 42
    }
  ]
}
```

### Filtering by Vehicle Count

You can filter operators by their vehicle count using the following parameters:

- `vehicle_count`: Minimum vehicle count (greater than or equal)
- `vehicle_count__lte`: Maximum vehicle count (less than or equal)
- `vehicle_count__exact`: Exact vehicle count

**Example Request** (operators with at least 10 vehicles):
```bash
curl "https://your-domain.com/api/operators/?vehicle_count=10"
```

**Example Request** (operators with between 10 and 50 vehicles):
```bash
curl "https://your-domain.com/api/operators/?vehicle_count=10&vehicle_count__lte=50"
```

**Example Request** (operators with exactly 25 vehicles):
```bash
curl "https://your-domain.com/api/operators/?vehicle_count__exact=25"
```

### Example Response

```json
{
  "noc": "TEST",
  "external_id": "",
  "slug": "test-operator",
  "name": "Test Operator",
  "slogan": "",
  "logo": null,
  "aka": "",
  "preserved": false,
  "ceased_operations_on": null,
  "vehicle_mode": "bus",
  "mode": "bus",
  "region_id": null,
  "url": "https://example.com",
  "twitter": "",
  "social_x": "",
  "social_fb": "",
  "social_instagram": "",
  "social_linkedin": "",
  "social_youtube": "",
  "social_tiktok": "",
  "social_threads": "",
  "social_bluesky": "",
  "social_mastodon": "",
  "social_other": "",
  "garages": []
}
```

### Updating an Operator

**Endpoint**: `PUT /api/operators/{noc}/` or `PATCH /api/operators/{noc}/`

```bash
curl -X PATCH https://your-domain.com/api/operators/TEST/ \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Test Operator"
  }'
```

### Deleting an Operator

**Endpoint**: `DELETE /api/operators/{noc}/`

```bash
curl -X DELETE https://your-domain.com/api/operators/TEST/ \
  -H "Authorization: Bearer YOUR_API_KEY"
```

## Security Notes

- Keep your API keys secret and secure
- Rotate API keys periodically
- Deactivate unused API keys in the admin
- API keys are tied to user accounts - ensure the user has appropriate permissions
- The `last_used_at` timestamp is updated on each authenticated request

## Error Responses

**Invalid API Key**:
```json
{
  "detail": "Invalid API key"

}
```

**Missing API Key**:
```json
{
  "detail": "Authentication credentials were not provided."
}
```

**Validation Error**:
```json
{
  "noc": ["This field is required."],
  "name": ["This field is required."]
}
```
