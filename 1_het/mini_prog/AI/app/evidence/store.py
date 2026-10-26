from app.evidence.schemas import ALIAS_PREFIX, Evidence, with_identity

CERTAINTY_RANK = {"direct": 2, "inferred": 1, "unresolved": 0}


class EvidenceScopeError(ValueError):
    pass


def _union(first: list, second: list) -> list:
    merged = list(first)
    for value in second:
        if value not in merged:
            merged.append(value)
    return merged


def merge_evidence(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    merged["produced_by"] = _union(existing.get("produced_by") or [], incoming.get("produced_by") or [])

    scores = [s for s in (existing.get("retrieval_score"), incoming.get("retrieval_score")) if s is not None]
    merged["retrieval_score"] = max(scores) if scores else None

    if len(incoming.get("content") or "") > len(existing.get("content") or ""):
        merged["content"] = incoming.get("content")
        merged["source_type"] = incoming.get("source_type", existing.get("source_type"))

    if CERTAINTY_RANK.get(incoming.get("certainty"), 0) > CERTAINTY_RANK.get(existing.get("certainty"), 0):
        merged["certainty"] = incoming["certainty"]

    for key in ("symbol_id", "symbol_name", "symbol_kind", "language"):
        if not merged.get(key) and incoming.get(key):
            merged[key] = incoming[key]

    merged["metadata"] = {**(incoming.get("metadata") or {}), **(existing.get("metadata") or {})}
    return merged


def merge_evidence_maps(left: dict | None, right: dict | None) -> dict:
    result = dict(left or {})
    for evidence_id, item in (right or {}).items():
        result[evidence_id] = merge_evidence(result[evidence_id], item) if evidence_id in result else item
    return result


class EvidenceStore:
    def __init__(
        self,
        project_id: int | None,
        snapshot: str,
        items: dict | None = None,
        aliases: dict | None = None,
        capacity: int = 1000,
    ):
        self.project_id = project_id
        self.snapshot = snapshot
        self.items: dict[str, dict] = dict(items or {})
        aliases = aliases or {}
        self.by_alias: dict[str, list[str]] = {k: list(v) for k, v in (aliases.get("by_alias") or {}).items()}
        self.by_key: dict[str, str] = dict(aliases.get("by_key") or {})
        self.capacity = capacity
        self.rejected: list[dict] = []

    @staticmethod
    def from_state(state: dict, capacity: int = 1000) -> "EvidenceStore":
        return EvidenceStore(
            project_id=state.get("project_id"),
            snapshot=state.get("repository_snapshot", ""),
            items=state.get("evidence"),
            aliases=state.get("aliases"),
            capacity=capacity,
        )

    def aliases_state(self) -> dict:
        return {"by_alias": self.by_alias, "by_key": self.by_key}

    def _alias_key(self, evidence: Evidence) -> str:
        if evidence.family in ("rel", "node") and evidence.group:
            return f"group:{evidence.group}"
        return evidence.evidence_id

    def _assign_alias(self, evidence: Evidence) -> str:
        key = self._alias_key(evidence)
        alias = self.by_key.get(key)
        if alias is None:
            prefix = ALIAS_PREFIX[evidence.family]
            count = sum(1 for existing in self.by_alias if existing.startswith(prefix + "_"))
            alias = f"{prefix}_{count + 1}"
            self.by_key[key] = alias
            self.by_alias[alias] = []
        if evidence.evidence_id not in self.by_alias[alias]:
            self.by_alias[alias].append(evidence.evidence_id)
        return alias

    def add(self, evidence: Evidence) -> tuple[str | None, bool]:
        if evidence.project_id is not None and self.project_id is not None and evidence.project_id != self.project_id:
            self.rejected.append({"reason": "project_mismatch", "producedBy": evidence.produced_by})
            raise EvidenceScopeError("evidence belongs to a different project")
        if evidence.repository_snapshot and evidence.repository_snapshot != self.snapshot:
            self.rejected.append({"reason": "snapshot_mismatch", "producedBy": evidence.produced_by})
            raise EvidenceScopeError("evidence belongs to a different repository snapshot")

        stamped = with_identity(evidence.model_copy(update={
            "project_id": self.project_id,
            "repository_snapshot": self.snapshot,
        }))
        payload = stamped.model_dump()

        if stamped.evidence_id in self.items:
            self.items[stamped.evidence_id] = merge_evidence(self.items[stamped.evidence_id], payload)
            self._assign_alias(stamped)
            return stamped.evidence_id, False

        if len(self.items) >= self.capacity:
            self.rejected.append({"reason": "capacity", "producedBy": evidence.produced_by})
            return None, False

        self.items[stamped.evidence_id] = payload
        self._assign_alias(stamped)
        return stamped.evidence_id, True

    def get(self, evidence_id: str) -> Evidence | None:
        item = self.items.get(evidence_id)
        return Evidence.model_validate(item) if item else None

    def all(self) -> list[Evidence]:
        return [Evidence.model_validate(item) for item in self.items.values()]

    def alias_for(self, evidence_id: str) -> str | None:
        for alias, ids in self.by_alias.items():
            if evidence_id in ids:
                return alias
        return None

    def ids_for(self, alias: str) -> list[str]:
        return list(self.by_alias.get(alias, []))

    def evidence_for(self, alias: str) -> list[Evidence]:
        return [e for e in (self.get(i) for i in self.ids_for(alias)) if e is not None]

    def __len__(self) -> int:
        return len(self.items)
