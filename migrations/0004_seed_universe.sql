-- Seed the default static universe into the active strategy_config when not yet defined.
-- Idempotent: only fires when settings_json has no "universe" key.

UPDATE strategy_configs
SET settings_json = json_set(
        COALESCE(NULLIF(settings_json, ''), '{}'),
        '$.universe',
        json('["NVDA","AMD","SPY","QQQ","SOXL","TSLA","MSFT","AAPL","META","GOOGL"]')
    ),
    updated_ts = strftime('%s','now')
WHERE name = 'default'
  AND is_active = 1
  AND (
      settings_json IS NULL
      OR settings_json = ''
      OR json_extract(settings_json, '$.universe') IS NULL
  );
