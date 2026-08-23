-- Mocked identity. Identity may be mocked; AUTHORISATION may not.
-- The resolver looks the claimed X-User-Id up here and fails closed.
CREATE TABLE IF NOT EXISTS users (
  user_id      TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role         TEXT NOT NULL,   -- customer | support_agent | ops_lead
  account_id   TEXT             -- NULL for internal staff
);

-- Two customers on DIFFERENT accounts, so the access-control demo is one click
-- and the leak tests have a real second account to fail against.
INSERT INTO users (user_id, display_name, role, account_id) VALUES
  ('u_northstar', 'Dana (Northstar Logistics)', 'customer',      'ACCT-001'),
  ('u_lumen',     'Sam (LumenWorks)',           'customer',      'ACCT-002'),
  ('u_beacon',    'Ravi (Beacon Retail)',       'customer',      'ACCT-003'),
  ('u_agent',     'Maya (Support Agent)',       'support_agent', NULL),
  ('u_ops',       'Rohit (Ops Lead)',           'ops_lead',      NULL)
ON CONFLICT (user_id) DO NOTHING;
