# Phase 10 local persistence

P10.1–P10.3 add local Postgres/pgvector and DynamoDB Local without switching
normal application runtime away from Firestore. These commands need no cloud
account, AWS credentials, or Neon credentials. The local AWS keys in the examples
are dummy values used only with the explicit DynamoDB Local endpoint.

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

The application still selects Firestore in its normal runtime factory until
the separately authorized migration/backfill and cutover work is complete.
