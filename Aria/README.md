# Aria
Auto update repo for Aria selfbot!

Real slash command bot setup: see `REAL_SLASH_SETUP.md`.

## MongoDB backend

Aria can store hot runtime state in MongoDB instead of repeatedly writing JSON files.

Enable it in `config.json`:

```json
{
	"mongo_enabled": true,
	"mongo_uri": "mongodb://127.0.0.1:27017",
	"mongo_database": "aria",
	"mongo_collection": "app_state",
	"mongo_timeout_ms": 1500
}
```

Install the driver in the active Python environment:

```bash
pip install pymongo
```

Current Mongo-backed runtime datasets:

- `history_data`
- `account_stats`
- `analytics`
- `dashboard_users`
- `access_requests`

If MongoDB is disabled or unavailable, Aria falls back to the existing JSON files automatically.
