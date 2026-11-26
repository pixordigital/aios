import asyncio
from sqlalchemy import text
from aios.db.backend import db_session

async def main():
    async with db_session() as db:
        orgs = (await db.execute(text("SELECT id,name,slug,is_active FROM organizations ORDER BY name"))).all()
        print("ORGS", orgs)
        users = (await db.execute(text("SELECT id,email,role,org_id FROM users WHERE lower(email)='pixordigital@gmail.com'"))).all()
        print("USERS", users)
        mems = (await db.execute(text("SELECT m.role,o.slug,o.id FROM organization_memberships m JOIN organizations o ON o.id=m.org_id JOIN users u ON u.id=m.user_id WHERE lower(u.email)='pixordigital@gmail.com'"))).all()
        print("MEMS", mems)

if __name__ == "__main__":
    asyncio.run(main())
