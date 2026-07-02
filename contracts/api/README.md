# api/ — frontend ⇄ backend contract

See `api_contract.md`. Freeze before fan-out. SSE for both chat surfaces. Every
endpoint is auth-scoped server-side; never trust client-supplied identity.
