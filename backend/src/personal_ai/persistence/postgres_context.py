"""Postgres adapters for AI-owned context profile records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from personal_ai.auth.scope import STANDALONE_APPLICATION_ID, ApplicationScope
from personal_ai.context.profile import (
    GlobalProfile,
    GlobalProfileFieldRecord,
    GlobalProfileRepository,
    GlobalProfileUpdate,
    ProfileField,
)
from personal_ai.persistence.postgres import (
    PersistenceConflict,
    PersistenceRecordNotFound,
    PostgresDatabase,
    PostgresPayloadRepository,
    _ensure_namespace,
    _is_unique_violation,
)

_PROFILE_SCOPE = ApplicationScope(application_id=STANDALONE_APPLICATION_ID)
_PROFILE_RECORD_ID = "owner-global-profile-v1"


class PostgresGlobalProfileRepository(GlobalProfileRepository):
    """Owner-wide profile in Postgres with CAS updates and filtered share reads."""

    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    @staticmethod
    def _decode(payload, owner_id: str) -> GlobalProfile:
        try:
            profile = GlobalProfile.model_validate(payload)
        except (ValueError, TypeError) as error:
            raise RuntimeError("global_profile_record_invalid") from error
        if profile.owner_id != owner_id:
            raise PersistenceRecordNotFound("profile not found")
        return profile

    def get(self, owner_id: str) -> GlobalProfile:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM global_profiles WHERE scope_id=%s AND record_id=%s "
                "AND owner_id=%s AND application_id=%s AND workspace_id IS NULL",
                (
                    PostgresPayloadRepository.scope_id(owner_id, _PROFILE_SCOPE),
                    _PROFILE_RECORD_ID,
                    owner_id,
                    STANDALONE_APPLICATION_ID,
                ),
            ).fetchone()
        if row is None:
            return GlobalProfile(owner_id=owner_id, revision=0, fields=(), updated_at=None)
        return self._decode(row[0], owner_id)

    def update(self, owner_id: str, update: GlobalProfileUpdate) -> GlobalProfile:
        if not owner_id or len(owner_id) > 200:
            raise ValueError("owner_id_invalid")
        now = datetime.now(UTC)
        for attempt in range(3):
            try:
                with self.database.transaction() as connection:
                    scope_id = _ensure_namespace(connection, owner_id, _PROFILE_SCOPE)
                    row = connection.execute(
                        "SELECT payload,revision FROM global_profiles WHERE scope_id=%s "
                        "AND record_id=%s AND owner_id=%s AND application_id=%s "
                        "AND workspace_id IS NULL FOR UPDATE",
                        (scope_id, _PROFILE_RECORD_ID, owner_id, STANDALONE_APPLICATION_ID),
                    ).fetchone()
                    current = (
                        self._decode(row[0], owner_id)
                        if row is not None
                        else GlobalProfile(owner_id=owner_id, revision=0, fields=(), updated_at=None)
                    )
                    fields = {item.field: item for item in current.fields}
                    for name in update.remove_fields:
                        fields.pop(name, None)
                    for item in update.fields:
                        fields[item.field] = GlobalProfileFieldRecord(
                            **item.model_dump(), set_by="user", set_at=now
                        )
                    candidate = GlobalProfile(
                        owner_id=owner_id,
                        revision=current.revision + 1,
                        fields=tuple(fields[key] for key in sorted(fields)),
                        updated_at=now,
                    )
                    serialized = PostgresPayloadRepository._json(
                        candidate.model_dump(mode="json")
                    )
                    if row is None:
                        connection.execute(
                            "INSERT INTO global_profiles(record_id,scope_id,owner_id,application_id,"
                            "workspace_id,record_version,revision,created_at,updated_at,payload) "
                            "VALUES (%s,%s,%s,%s,NULL,1,%s,%s,%s,%s::jsonb)",
                            (
                                _PROFILE_RECORD_ID,
                                scope_id,
                                owner_id,
                                STANDALONE_APPLICATION_ID,
                                candidate.revision,
                                now,
                                now,
                                serialized,
                            ),
                        )
                    else:
                        cursor = connection.execute(
                            "UPDATE global_profiles SET payload=%s::jsonb,revision=%s,updated_at=%s "
                            "WHERE scope_id=%s AND record_id=%s AND owner_id=%s "
                            "AND application_id=%s AND workspace_id IS NULL AND revision=%s",
                            (
                                serialized,
                                candidate.revision,
                                now,
                                scope_id,
                                _PROFILE_RECORD_ID,
                                owner_id,
                                STANDALONE_APPLICATION_ID,
                                int(row[1]),
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise PersistenceConflict("profile revision changed")
                return candidate
            except Exception as error:
                if _is_unique_violation(error):
                    if attempt < 2:
                        continue
                    raise PersistenceConflict("profile update contention") from error
                raise
        raise PersistenceConflict("profile update contention")

    def shared_fields(
        self,
        owner_id: str,
        application_id: str,
        fields: Sequence[ProfileField],
        *,
        deadline: float | None = None,
    ) -> tuple[tuple[int, GlobalProfileFieldRecord], ...]:
        if not fields:
            return ()
        with self.database.connection(deadline=deadline) as connection:
            rows = connection.execute(
                "SELECT gp.revision,fields.value FROM global_profiles AS gp "
                "CROSS JOIN LATERAL jsonb_array_elements(gp.payload->'fields') AS fields(value) "
                "WHERE gp.scope_id=%s AND gp.record_id=%s AND gp.owner_id=%s "
                "AND gp.application_id=%s AND gp.workspace_id IS NULL "
                "AND fields.value->>'field'=ANY(%s) "
                "AND COALESCE(fields.value->'shared_with_applications','[]'::jsonb) ? %s "
                "ORDER BY fields.value->>'field' LIMIT 4",
                (
                    PostgresPayloadRepository.scope_id(owner_id, _PROFILE_SCOPE),
                    _PROFILE_RECORD_ID,
                    owner_id,
                    STANDALONE_APPLICATION_ID,
                    list(fields),
                    application_id,
                ),
            ).fetchall()
        try:
            return tuple(
                (int(revision), GlobalProfileFieldRecord.model_validate(field))
                for revision, field in rows
            )
        except (ValueError, TypeError) as error:
            raise RuntimeError("global_profile_share_record_invalid") from error
