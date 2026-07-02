# config_schema/ — THE central contract

`schema.py` = the agent's data shape. `field_policy.py` = who controls each field
(locked/default/open × platform/user) and which fields form the completeness model.

Data and policy are separated on purpose: the gate enforces policy, the panel
renders both, the builder generates against both.

**Do not** add capabilities here that the runtime can't honor — a field's presence
implies the agent can act on it (D13). Wishlist items live in `AgentConfig.wishlist`.
