# Xray Log Compatibility Contract

## Purpose
Define parser compatibility by **log text contract** rather than source-code dependency.

## Scope
- Access log parsing (`parse_line` -> `access` event)
- DNS log parsing (`parse_line` -> `dns` event)
- Error log parsing (`parse_error_line`)

## Supported Timestamp Prefix
Accepted formats:
- `YYYY/MM/DD HH:MM:SS.ffffff`
- `YYYY/MM/DD HH:MM:SS`

## Access Contract
Expected body pattern after timestamp:
- `from <src> <accepted|rejected> <dest> [<inbound -> outbound>] <tail>`
- Optional email in tail: `email: <value>`

Extracted fields:
- `src`, `status`, `dest_raw`, `dest_host`, `dest_port`, `detour`
- `user_email` (default `unknown`)
- `is_domain`, `confidence`

Known boundaries:
- URL path/query is out of scope.
- IP direct traffic keeps IP as destination host.

## DNS Contract
Expected body pattern after timestamp:
- `<server> <got answer:|cache HIT:|cache OPTIMISTE:> <domain> -> [ip1, ip2] <tail>`

Extracted fields:
- `dns_server`, `domain`, `ips_json`, `dns_status`, `elapsed_ms`, `error_text`

Known boundaries:
- DNS events are not hard-bound to specific user identity.

## Error Contract
Expected pattern:
- `[Level] [session_id optional] [component optional]: message`

Level support:
- `debug`, `info`, `warning`, `error`, fallback `unknown`

Extracted fields:
- `event_time`, `level`, `session_id`, `component`, `message`
- optional `src`, `dest_raw`, `dest_host`, `dest_port`
- derived: `category`, `signature_hash`, `is_noise`

## Test Fixtures
Compatibility is validated by fixtures under `tests/fixtures/`:
- `access_samples.log`
- `dns_samples.log`
- `error_samples.log`

Regression tests:
- parser tests (`tests/test_parser.py`)
- error parser tests (`tests/test_error_parser.py`)
- log contract fixtures (`tests/test_log_contract.py`)

## Upgrade Policy
When onboarding a new Xray build:
1. Collect representative access/error sample lines.
2. Add or update fixture files.
3. Update parser rules only if needed.
4. Ensure all tests pass before release.

## Source Reference Policy
- Keep an external note of observed Xray release tag/commit.
- Do not vendor or publish Xray source code in this repository.
