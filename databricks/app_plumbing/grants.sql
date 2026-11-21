-- Grants for the referral-saathi app service principal (application id below).
-- SELECT is granted on the schema, so it covers every current table and any table the loader adds or replaces.
-- MODIFY is granted on call_outcomes only: the app writes nothing else.
GRANT USE CATALOG ON CATALOG workspace TO `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`;
GRANT USE SCHEMA ON SCHEMA workspace.referral_saathi TO `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`;
GRANT SELECT ON SCHEMA workspace.referral_saathi TO `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`;
GRANT MODIFY ON TABLE workspace.referral_saathi.call_outcomes TO `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`;
