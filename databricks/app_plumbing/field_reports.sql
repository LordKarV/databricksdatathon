-- Field reports (community-features): extend call_outcomes instead of adding a table. Apply after
-- call_outcomes.sql, once. The app keeps writing the old row shape until this runs (it writes a new column only
-- when it has a value), but visit reports and reporter keys fail until it has run.
--
-- Still NO PATIENT DATA and NO REPORTER IDENTITY: reason and wait_bucket are fixed enums (never free text), and
-- reporter_key is HMAC-SHA256(app secret, signed-in user) cut to 16 hex characters, never the user or email.
--
-- The secret behind reporter_key (the lead creates it; the value never goes in git):
--   databricks secrets create-scope referral-saathi
--   databricks secrets put-secret referral-saathi reporter-key --string-value "$(openssl rand -hex 32)"
-- App resource (add to app_resources.json):
--   {"name": "reporter-key", "secret": {"scope": "referral-saathi", "key": "reporter-key", "permission": "READ"}}
-- app.yaml env entry (tools/deploy/deploy.sh writes app.yaml):
--   - name: REPORTER_KEY
--     valueFrom: reporter-key
-- Without it the app stores reporter_key NULL; such rows are not rate limited and never count as a reporter.

ALTER TABLE workspace.referral_saathi.call_outcomes ADD COLUMNS (
  kind STRING COMMENT 'call (phone outcome) or visit (the patient went: accepted or turned_away). NULL = call (rows from before field reports)',
  reason STRING COMMENT 'Why a no or a turn-away, fixed list. Does not offer: service_not_here, equipment_absent, referred_elsewhere_for_this_service. Temporary: no_bed, doctor_absent, machine_down, asked_to_pay, closed_now. Never free text',
  wait_bucket STRING COMMENT 'Visit only: lt_30m, 30_120m or gt_2h',
  reporter_key STRING COMMENT 'HMAC-SHA256(REPORTER_KEY secret, signed-in user)[:16]; counts distinct reporters, never identifies them. NULL when the app has no key'
);

-- The old check allowed only phone answers; replace it with one that pairs outcome with kind.
ALTER TABLE workspace.referral_saathi.call_outcomes DROP CONSTRAINT IF EXISTS outcome_valid;
ALTER TABLE workspace.referral_saathi.call_outcomes ADD CONSTRAINT outcome_valid CHECK (
  (coalesce(kind, 'call') = 'call' AND outcome IN ('yes', 'no', 'no_answer'))
  OR (kind = 'visit' AND outcome IN ('accepted', 'turned_away')));
ALTER TABLE workspace.referral_saathi.call_outcomes ADD CONSTRAINT reason_valid CHECK (reason IS NULL OR (
  outcome IN ('no', 'turned_away') AND reason IN ('service_not_here', 'equipment_absent',
  'referred_elsewhere_for_this_service', 'no_bed', 'doctor_absent', 'machine_down', 'asked_to_pay', 'closed_now')));
ALTER TABLE workspace.referral_saathi.call_outcomes ADD CONSTRAINT wait_bucket_valid CHECK (wait_bucket IS NULL OR (
  kind = 'visit' AND wait_bucket IN ('lt_30m', '30_120m', 'gt_2h')));
ALTER TABLE workspace.referral_saathi.call_outcomes ADD CONSTRAINT reporter_key_shape CHECK (
  reporter_key IS NULL OR reporter_key RLIKE '^[0-9a-f]{16}$');

COMMENT ON TABLE workspace.referral_saathi.call_outcomes IS 'Call and visit outcomes for the learning loop (issue #65) and field reports: after a referral, the health worker reports what the facility said on the phone, or whether the patient was accepted. Written only by the referral-saathi app. NO PATIENT DATA MAY BE STORED: no names, phone numbers, ages, conditions, free-text notes, raw GPS or addresses. No reporter identity: reporter_key is a keyed hash. District is the finest location allowed.';

-- Undo:
-- ALTER TABLE workspace.referral_saathi.call_outcomes DROP CONSTRAINT IF EXISTS reporter_key_shape;
-- ALTER TABLE workspace.referral_saathi.call_outcomes DROP CONSTRAINT IF EXISTS wait_bucket_valid;
-- ALTER TABLE workspace.referral_saathi.call_outcomes DROP CONSTRAINT IF EXISTS reason_valid;
-- ALTER TABLE workspace.referral_saathi.call_outcomes DROP CONSTRAINT IF EXISTS outcome_valid;
-- DELETE FROM workspace.referral_saathi.call_outcomes WHERE kind = 'visit';
-- ALTER TABLE workspace.referral_saathi.call_outcomes ADD CONSTRAINT outcome_valid CHECK (outcome IN ('yes', 'no', 'no_answer'));
-- (Dropping columns needs column mapping on Delta; leaving the four NULL-able columns in place is harmless.)
