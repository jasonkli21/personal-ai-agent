# Phase 10 local persistence

The Phase 10 cutover is implemented locally. Local and test application
configurations use explicit Postgres/pgvector and DynamoDB Local endpoints;
staging and production use Neon/Postgres and DynamoDB through the configured
runtime adapters. Firestore runtime adapters and fallback configuration have
been removed. This guide covers the local persistence commands and isolated
integration checks. They need no cloud account, AWS credentials, or Neon
credentials. The local AWS keys in the examples are dummy values used only with
the explicit DynamoDB Local endpoint.

## Start and stop the development stores

From the repository root:

```sh
make persistence-up
make persistence-ready
make persistence-bootstrap
```

Postgres is available at `postgresql://personal_ai:personal_ai_local_only@127.0.0.1:54329/personal_ai`.
DynamoDB Local is available at `http://127.0.0.1:8000`. The first `make
persistence-bootstrap` installs the versioned Postgres schema and creates the
runtime table and its single sparse publication index. Development data lives
in named Docker volumes and survives ordinary `down`/`up` cycles.

```sh
make persistence-down
```

That stops containers and preserves the development volumes. To explicitly
delete local development data, run `make persistence-clean`; it removes only
the named persistence volumes from `docker-compose.persistence.yml`.

## Isolated integration checks

```sh
make persistence-test-up
make persistence-test
make persistence-test-down
```

The integration profile uses a separate disposable Postgres instance backed by
`tmpfs` and an in-memory DynamoDB Local instance. It never points tests at the
development databases. The `down` target removes the disposable containers.
The persistence tests also support explicit `PERSISTENCE_TEST_POSTGRES_DSN` and
`PERSISTENCE_TEST_DYNAMODB_ENDPOINT` values for an equivalent isolated local
setup. They do not discover cloud credentials or fall back to AWS.

## Environment safety

Postgres and DynamoDB Local endpoints are accepted only in `local` and `test`
environments. Staging/production reject localhost persistence endpoints. The
runtime clients require an explicit DynamoDB endpoint when configured for local
use and pass dummy credentials directly to the SDK, so local checks cannot use
the AWS credential-provider chain. No Neon, IAM, or provider configuration is
introduced by these local commands.

The local commands do not configure Neon, cloud IAM, or model providers. Cloud
provisioning and the remaining target-store acceptance checks are documented in
the [GCP deployment guide](gcp-deployment.md) and [Phase 10 verification plan](personal-ai-chapter-2/phase-10-migration-cutover-and-verification-plan.md).
