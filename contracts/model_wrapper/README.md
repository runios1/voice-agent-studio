# model_wrapper/ — provider-agnostic interface

See `interface.py`. Every model call goes through `ModelWrapper`. Provider SDKs
are imported ONLY inside `backend/wrapper_impl`. Security screening decorates any
implementation (see `backend/security`). Builder and voice models may differ (D9).
