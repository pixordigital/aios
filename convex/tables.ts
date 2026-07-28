/// Generic CRUD queries and mutations for all AIOS tables.
/// Each table gets: get(id), list(filters), create(data), update(id,data), delete(id).
///
/// Python ConvexBackend calls these as: `tables:{operation}` with params.
/// The `table` param determines which Convex table to operate on.

import { v } from "convex/values";
import { query, mutation, QueryCtx, MutationCtx } from "./_generated/server";
import { Doc, Id } from "./_generated/dataModel";

const TABLES = [
  "organizations", "users", "agents", "agent_instances",
  "teams", "conversations", "messages", "channel_connections",
  "artifacts", "tools", "memories", "usage_records",
  "remote_instances", "invitations", "audit_logs", "oauth_accounts",
] as const;

type TableName = (typeof TABLES)[number];

function castTable(t: string): TableName {
  if (TABLES.includes(t as TableName)) return t as TableName;
  throw new Error(`Unknown table: ${t}`);
}

// ─── get(id) ───

export const get = query({
  args: { table: v.string(), id: v.string() },
  handler: async (ctx, args) => {
    const table = castTable(args.table);
    return await ctx.db.query(table).filter((q) => q.eq(q.field("_id"), args.id)).first();
  },
});

// ─── list(filters) ───

export const list = query({
  args: { table: v.string(), filters: v.optional(v.any()) },
  handler: async (ctx, args) => {
    const table = castTable(args.table);
    let q = ctx.db.query(table);
    const filters = args.filters ?? {};
    for (const [key, value] of Object.entries(filters)) {
      q = q.filter((f) => f.eq(f.field(key), value));
    }
    return await q.collect();
  },
});

// ─── count(filters) ───

export const count = query({
  args: { table: v.string(), filters: v.optional(v.any()) },
  handler: async (ctx, args) => {
    const table = castTable(args.table);
    let q = ctx.db.query(table);
    const filters = args.filters ?? {};
    for (const [key, value] of Object.entries(filters)) {
      q = q.filter((f) => f.eq(f.field(key), value));
    }
    return (await q.collect()).length;
  },
});

// ─── create(data) ───

export const create = mutation({
  args: { table: v.string(), data: v.any() },
  handler: async (ctx, args) => {
    const table = castTable(args.table);
    return await ctx.db.insert(table, args.data);
  },
});

// ─── update(id, data) ───

export const update = mutation({
  args: { table: v.string(), id: v.string(), data: v.any() },
  handler: async (ctx, args) => {
    const table = castTable(args.table);
    await ctx.db.patch(args.id as Id<typeof table>, args.data);
  },
});

// ─── delete(id) ───

export const del = mutation({
  args: { table: v.string(), id: v.string() },
  handler: async (ctx, args) => {
    const table = castTable(args.table);
    await ctx.db.delete(args.id as Id<typeof table>);
  },
});
