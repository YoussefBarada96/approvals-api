-- Runs once, the first time the Postgres container starts with an empty volume.
-- The test suite uses its own database so it never touches development data.
CREATE DATABASE approvals_test OWNER approvals;
