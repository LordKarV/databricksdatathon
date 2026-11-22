-- Grants for the referral-saathi app service principal (application id below).
-- Least privilege (#82 H5): the app reads its data from bundled files, so it gets SELECT and MODIFY on call_outcomes only.
-- MODIFY is granted on call_outcomes only: the app writes nothing else.
GRANT USE CATALOG ON CATALOG workspace TO `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`;
GRANT USE SCHEMA ON SCHEMA workspace.referral_saathi TO `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`;
GRANT SELECT, MODIFY ON TABLE workspace.referral_saathi.call_outcomes TO `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`;

-- Gold labels live in a separate schema with no app or dashboard grant; sealed TEST labels are never loaded before publication.
CREATE SCHEMA IF NOT EXISTS workspace.referral_saathi_eval;
