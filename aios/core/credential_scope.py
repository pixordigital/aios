"""Credential access scoping, shared by tools before they decrypt a credential."""

from sqlalchemy import and_, or_, select

from aios.db.models import Credential, CredentialScope, Team, team_agents


async def resolve_scoped_credential(sess, credential_id: str, *, org_id: str, agent_id: str, tool_name: str) -> Credential | None:
    """Return credential only if caller matches its explicit scopes.

    No scope rows means legacy access within the caller's org. Any rows present
    require an explicit agent/tool/team match; missing org/agent/tool context,
    cross-org rows, and mismatches fail closed. No decryption or secret logging
    happens here.
    """
    if not credential_id or not org_id:
        return None

    stmt = select(Credential).where(
        Credential.id == credential_id,
        Credential.org_id == org_id,
    )
    cred = (await sess.execute(stmt)).scalar_one_or_none()
    if cred is None:
        return None

    has_scopes = (
        await sess.execute(
            select(CredentialScope.id).where(CredentialScope.credential_id == cred.id).limit(1)
        )
    ).first() is not None
    if not has_scopes:
        return cred

    if not (org_id and agent_id and tool_name) or cred.org_id != org_id:
        return None

    match = (
        await sess.execute(
            select(CredentialScope.id)
            .outerjoin(Team, and_(Team.id == CredentialScope.scope_id, Team.org_id == cred.org_id))
            .outerjoin(
                team_agents,
                and_(team_agents.c.team_id == Team.id, team_agents.c.agent_id == agent_id),
            )
            .where(
                CredentialScope.credential_id == cred.id,
                CredentialScope.org_id == cred.org_id,
                or_(
                    and_(
                        CredentialScope.scope_type == "agent",
                        CredentialScope.scope_id == agent_id,
                    ),
                    and_(
                        CredentialScope.scope_type == "tool",
                        CredentialScope.scope_id == tool_name,
                    ),
                    and_(
                        CredentialScope.scope_type == "team",
                        Team.id.is_not(None),
                        team_agents.c.agent_id.is_not(None),
                    ),
                ),
            )
            .limit(1)
        )
    ).first()
    return cred if match else None
