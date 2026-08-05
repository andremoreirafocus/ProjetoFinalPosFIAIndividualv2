-- Least-privilege provisioning for the automated test suite.
--
-- Runs automatically on first cluster init (as superuser 'airflow', connected to
-- the 'airflow' database), after 01 has created 'data'. Written idempotently so it
-- can also be applied by hand to an already-initialized volume without harm.

-- 1. Least-privilege login role. NOSUPERUSER is what makes the CONNECT revoke below
--    binding: a superuser would bypass every grant.
DO $$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'data_test_user') THEN
      CREATE ROLE data_test_user LOGIN PASSWORD 'data_test'
         NOSUPERUSER NOCREATEDB NOCREATEROLE;
   END IF;
END
$$;

-- 2. Dedicated test database owned by that role. As owner it controls the 'public'
--    schema (PG15), so the suite can create/drop its own tables without extra grants.
--    CREATE DATABASE cannot run inside a transaction/DO block; gate it with \gexec.
SELECT 'CREATE DATABASE data_test OWNER data_test_user'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'data_test')\gexec

-- Reassert ownership so an already-existing 'data_test' (e.g. created earlier by a
-- superuser) is handed to the least-privilege role too. No-op on a fresh install.
ALTER DATABASE data_test OWNER TO data_test_user;

-- 3. The guarantee: remove PUBLIC's implicit CONNECT on the pipeline database so no
--    non-superuser (the test role included) can reach it. 'airflow' is a superuser
--    and is unaffected, so Airflow and the credit-api keep connecting to 'data'.
REVOKE CONNECT ON DATABASE data FROM PUBLIC;
